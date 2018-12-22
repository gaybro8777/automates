package org.clulab.aske.automates.apps

import java.io.File

import com.typesafe.config.{Config, ConfigFactory}
import org.clulab.aske.automates.OdinEngine
import org.clulab.utils.{Configured, FileUtils, Serializer}
import org.clulab.odin.Mention


/**
  * App used to extract mentions from files in a directory and produce the desired output format (i.e., serialized
  * mentions or any other format we may need).  The input and output directories as well as the desired export
  * formats are specified in the config file (located in src/main/resources).
  * This makes ONE output file for each of the input files.
  */
object ExtractAndExport extends App with Configured {

  def getExporter(exporterString: String, filename: String): Exporter = {
    exporterString match {
      case "serialized" => SerializedExporter(filename)
      case _ => throw new NotImplementedError(s"Export mode $exporterString is not supported.")
    }
  }

  val config = ConfigFactory.load("eidos")
  override def getConf: Config = config

  val inputDir = getArgString("apps.inputDirectory", None)
  val outputDir = getArgString("apps.outputDirectory", None)
  val inputExtension = getArgString("apps.inputFileExtension", None)
  val exportAs = getArgStrings("apps.exportAs", None)
  val files = FileUtils.findFiles(inputDir, inputExtension)
  val reader = new OdinEngine()

  // For each file in the input directory:
  files.par.foreach { file =>
    // 1. Open corresponding output file and make all desired exporters
    println(s"Extracting from ${file.getName}")
    // 2. Get the input file contents
    val text = FileUtils.getTextFromFile(file)
    // 3. Extract causal mentions from the text
    val mentions = reader.extractFromText(text, filename = Some(file.getName))
    // 4. Export to all desired formats
    exportAs.foreach { format =>
        val exporter = getExporter(format, s"$outputDir/${file.getName}")
        exporter.export(mentions)
        exporter.close() // close the file when you're done
    }
  }
}

trait Exporter {
  def export(mentions: Seq[Mention]): Unit
  def close(): Unit // for closing the file, if needed
}


case class SerializedExporter(filename: String) extends Exporter {
  override def export(mentions: Seq[Mention]): Unit = {
    Serializer.save[SerializedMentions](new SerializedMentions(mentions), filename + ".serialized")
  }

  override def close(): Unit = ()
}

// Helper Class to facilitate serializing the mentions
@SerialVersionUID(1L)
class SerializedMentions(val mentions: Seq[Mention]) extends Serializable {}
object SerializedMentions {
  def load(file: File): Seq[Mention] = Serializer.load[SerializedMentions](file).mentions 
  def load(filename: String): Seq[Mention] = Serializer.load[SerializedMentions](filename).mentions
}


object ExporterUtils {

  def removeTabAndNewline(s: String) = s.replaceAll("(\\n|\\t)", " ")
}
