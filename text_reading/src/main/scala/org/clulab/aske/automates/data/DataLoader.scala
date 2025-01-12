package org.clulab.aske.automates.data

import java.io.File

import ai.lum.common.StringUtils._
import org.clulab.aske.automates.scienceparse.ScienceParseClient
import org.clulab.utils.FileUtils.getTextFromFile

import scala.util.matching.Regex


/**
  * This DataLoader abstract class is intended to be able to load information from files, with each file providing
  * a sequence of Strings.
  */
abstract class DataLoader {
  val extension: String
  def loadFile(f: File): Seq[String]
  def loadFile(filename: String): Seq[String] = loadFile(new File(filename))
//  // defaultExtension can always be overridden, but will hopefully make calls to this method easier...?
//  def loadCollection(collectionDir: String, extension: String = defaultExtension): Seq[Seq[String]] = findFiles(collectionDir, extension).map(loadFile)
}

object DataLoader {

  // Select the kind of data loader you want,
  // todo: (revisit?) here we are working on scientific papers, so if it's json here we assume it's from science parse
  def selectLoader(s: String): DataLoader = {
    s match {
      case "txt" => new PlainTextDataLoader
      case "json" => new ScienceParsedDataLoader
      case "pdf" => new PDFDataLoader
      case "tokenized_latex" => new TokenizedLatexDataLoader
    }
  }
}


class ScienceParsedDataLoader extends DataLoader {
  /**
    * Loader for documents which have been pre-processed with science parse (v1).  Each file contains a json representation
    * of the paper sections, here we will return the strings from each section as a Seq[String].
    *
    * @param f the File being loaded
    * @return string content of each section in the parsed pdf paper (as determined by science parse)
    */
  def loadFile(f: File): Seq[String] = {
    // todo: this approach should like be revisited to handle sections more elegantly, or to omit some, etc.
    //the heading and the text of the section are currently combined; might need to be revisted
    val scienceParseDoc = ScienceParseClient.mkDocument(f)
    scienceParseDoc.sections.map(_.headingAndText) ++ scienceParseDoc.abstractText
  }
  override val extension: String = "json"
}


class PDFDataLoader extends DataLoader {

  // FIXME read from somewhere
  val domain = "localhost"
  val port = "8080"

  // connect to science-parse server
  val client = new ScienceParseClient(domain, port)

  /**
    * Loader for pdf documents, will pre-processed with science parse (v1).  Each file
    * is parsed into a json representation of the paper sections, here we will return the strings from
    * each section as a Seq[String].
    *
    * @param f the File being loaded
    * @return string content of each section in the parsed pdf paper (as determined by science parse)
    */
  def loadFile(f: File): Seq[String] = {
    // todo: this approach should like be revisited to handle sections more elegantly, or to omit some, etc.
    //the heading and the text of the section are currently combined; might need to be revisted
    val jsonString = client.parsePdfToJson(f)
    val uJson = ujson.read(jsonString) //make a ujson value out of the json string we get from scienceParse; mkDocument does not work on plain string.
    val scienceParseDoc = ScienceParseClient.mkDocument(uJson)
    scienceParseDoc.sections.map(_.headingAndText) ++ scienceParseDoc.abstractText
  }
  override val extension: String = "pdf"
}


class PlainTextDataLoader extends DataLoader {
  /**
    * Loader for text files.  Here we will return the content of the file as a Seq[String] (with length 1).
    *
    * @param f the File being loaded
    * @return string content of file (wrapped in sequence)
    */
  def loadFile(f: File): Seq[String] = Seq(getTextFromFile(f))
  override val extension: String = "txt"
}


class TokenizedLatexDataLoader extends DataLoader {
  /**
    * Loader for tokenized latex files, in the format given as predictions by the opennmt seq2seq model.
    * Here we will return the content of the file as a Seq[String], where each equation is a single string,
    * and the equation "chunks" are separated by whitespace.
    *
    * @param f the File being loaded
    * @return chunked latex tokens from equations
    */
  def loadFile(f: File): Seq[String] = {
    getTextFromFile(f).split("\n")
  }
  override val extension: String = "txt"

  def chunkLatex(equation: String): Seq[String] = {
    // Used to merge derivatives, e.g., ("d", "S", ...) => ("dS", ...)
    // from https://stackoverflow.com/a/2427603
    def collapseDerivs(in: List[String], accum: List[String]): List[String] = in match {
      case x :: y :: ys if x == "d" => collapseDerivs( s"$x$y" :: ys, accum )
      case x :: xs => collapseDerivs( xs, x :: accum )
      case Nil => accum
    }

    def replacePattern(pattern: Regex, s: String): String = {
      var equation = s
      val matches = pattern.findAllMatchIn(equation)
      matches foreach { m =>
        val full = m.group(0).escapeRegex
        val inside = m.group(1).replaceAll(" ", "").escapeRegex
        equation = equation.replaceFirst(full, inside)
      }
      equation
    }

    // chunk
    val mathrmPattern = "\\\\mathrm \\{(.+)\\}".r
    val equation1 = replacePattern(mathrmPattern, equation)

    val oneArgFunctionPattern = "([a-zA-Z] \\( . \\))".r
    val equation2 = replacePattern(oneArgFunctionPattern, equation1)

    val tokens = equation2.split(" ")

    // keep the ones with alpha chars
    tokens.filter(_.exists(char => char.isLetter))
  }
}


//object Testy {
//  def main(args: Array[String]): Unit = {
//    val dir = args(0)
//    val loader = new ScienceParsedDataLoader
//    val files = findFiles(dir, "json")
//    files foreach { f =>
//      val doc = loader.loadFile(f)
//      println(s"Filename: ${f.getBaseName}")
//      println(doc.head)
//      println()
//    }
//  }
//}

