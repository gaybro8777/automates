#!/usr/bin/env python

from __future__ import division, print_function

import os
import re
import json
import argparse
import subprocess
import cv2
import jinja2
import numpy as np
from skimage import img_as_ubyte
from pdf2image import convert_from_path
from latex import LatexTokenizer, find_main_tex_file



def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('indir')
    parser.add_argument('--outdir', default='output')
    parser.add_argument('--logfile', default='collect_data.log')
    parser.add_argument('--template', default='misc/template.tex')
    parser.add_argument('--rescale-factor', type=float, default=1, help='rescale pages to speedup template matching')
    parser.add_argument('--dump-pages', action='store_true')
    parser.add_argument('--keep-intermediate-files', action='store_true')
    parser.add_argument('--pdfdir', help='directory with precompiled whole paper pdfs, if provided we will not regenerate them')
    args = parser.parse_args()
    return args



def render_tex(filename, outdir, keep_intermediate):
    """render latex document"""
    dirname = os.path.dirname(filename)
    basename = os.path.basename(filename)
    # we use -halt-on-error so that the latexmk dies if an error is encountered
    # so that we can move on to the next tex file
    command = ['latexmk', '-halt-on-error', '-outdir=' + outdir, '-pdf', basename]
    return_code = run_command(command, dirname, os.path.join(outdir, 'latexmk.logfile'))
    # we can remove the intermediate files generated by latexmk to save storage space
    if not keep_intermediate:
        # use -c to delete intermediate files, not the pdf
        command = ['latexmk', '-c', '-outdir=' + outdir]
        run_command(command, dirname, '/dev/null')
    if return_code == 0:
        pdf_name = os.path.join(outdir, os.path.splitext(basename)[0] + '.pdf')
    else:
        pdf_name = None
    return pdf_name



def run_command(cmd, dirname, log_fn):
    with open(log_fn, 'w') as logfile:
        p = subprocess.Popen(cmd, stdout=logfile, stderr=subprocess.STDOUT, cwd=dirname)
        p.communicate()
        return_code = p.wait()
        return return_code



def render_equation(equation, template, filename, keep_intermediate):
    dirname = os.path.dirname(filename)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    equation_tex = template.render(equation=equation)
    with open(filename, 'w') as f:
        f.write(equation_tex)
    pdf_name = render_tex(filename, dirname, keep_intermediate)
    if pdf_name:
        image = get_pages(pdf_name)[0]
    else:
        image = None
    return image



def get_pages(pdf_name):
    pages = []
    for img in convert_from_path(pdf_name):
        page = np.array(img)
        page = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
        pages.append(page)
    return pages



def match_template(pages, template, rescale_factor):
    # the margin is intended to add a bit of whitespace to account for slight differences
    # in the way various stylesheets affect the equation character spacing (i.e., so things
    # don't get clipped by the aabb)
    margin = 3
    best_val = -np.inf
    best_loc = (-1, -1)
    best_page = -1
    best_h, best_w = -1, -1 # essentially keeps track of the best scale factor
    # rescale pages and template to speed up template matching
    if rescale_factor != 1:
        template = cv2.resize(template, (0,0), fx=rescale_factor, fy=rescale_factor)
        pages = [cv2.resize(p, (0,0), fx=rescale_factor, fy=rescale_factor) for p in pages]
    # Try several scale factors in case the standalone equation is slightly smaller/bigger
    # than the one in the original paper
    for scale in np.linspace(0.8, 1.2, 5):
        # resize/scale the template
        resized = cv2.resize(template, (0,0), fx=scale, fy=scale)
        for i, page in enumerate(pages):
            result = cv2.matchTemplate(page, resized, cv2.TM_CCOEFF_NORMED)
            (min_val, max_val, min_loc, max_loc) = cv2.minMaxLoc(result)
            if best_val < max_val:
                best_val = max_val
                best_loc = max_loc
                best_page = i
                best_h, best_w = resized.shape[:2]
    # Note that we are adding the margin described above
    upper_left = (best_loc[0] - margin, best_loc[1] - margin)
    lower_right = (best_loc[0] + best_w + margin, best_loc[1] + best_h + margin)
    if rescale_factor != 1:
        upper_left = int(upper_left[0] / rescale_factor), int(upper_left[1] / rescale_factor)
        lower_right = int(lower_right[0] / rescale_factor), int(lower_right[1] / rescale_factor)
    return best_val, best_page, upper_left, lower_right



def list_paper_dirs(indir):
    """
    gets a directory that is expected to contain directories of the form
    `1810` which themselves would contain directories of the form `1810.04805`
    with the tex source for the corresponding paper in arxiv, and returns
    the directory paths to the directories with the papers source
    """
    for chunk in os.listdir(indir):
        if re.match(r'^\d{4}$', chunk):
            chunkdir = os.path.join(indir, chunk)
            for paper in os.listdir(chunkdir):
                if re.match(r'^\d{4}\.\d{5}$', paper):
                    yield os.path.join(chunkdir, paper)

# used to format error msgs for the poor man's log in process_paper()
def error_msg(paper_name, msg, equations=[]):
    eqns_failed = ', '.join(equations)
    return '\t'.join([paper_name, msg, eqns_failed]) + '\n'

def get_paper_id(dirname):
    return os.path.basename(os.path.normpath(dirname))  # e.g., 1807.07834

def process_paper(dirname, template, outdir, rescale_factor, dump_pages, keep_intermediate, pdfdir):
    # keep a poor man's log of what failed, if anything
    info_log = ''

    texfile = find_main_tex_file(dirname)
    paper_id = get_paper_id(dirname)  # e.g., 1807.07834
    # directory for whole paper
    outdir = os.path.abspath(os.path.join(outdir, paper_id[:4], paper_id)) # e.g., .../1807/1807.07834/
    # To restart gracefully after having crashed, check to see if we already processed this paper
    if os.path.exists(outdir):
        print("Paper ID already exists:", paper_id)
        return ''
    else:
        os.makedirs(outdir)
    # read latex tokens from document
    tokenizer = LatexTokenizer(texfile)
    # extract equations from token stream
    equations = tokenizer.equations()
    # compile pdf from document
    if pdfdir:
        # if given dir for pre-compiled pdfs, use that
        pdf_name = os.path.join(pdfdir, paper_id + ".pdf")
    else:
        # otherwise, render it from source
        pdf_name = render_tex(texfile, outdir, keep_intermediate)
    # if the pdf is there (rendered OR provided)
    if pdf_name:
        # retrieve pdf pages as images
        pages = get_pages(pdf_name)
        if dump_pages:
            os.makedirs(os.path.join(outdir, 'pages'))
            for i,p in enumerate(pages):
                img_name = os.path.join(outdir, 'pages', '%03d.png' % i)
                cv2.imwrite(img_name, p)
        # load jinja2 template
        template_loader = jinja2.FileSystemLoader(searchpath='.')
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template(template)
        # keep track of which eqns failed or were skipped, to hopefully later recover
        failed_eqns = []
        skipped_eqns = []
        for (i, (environment_name, eq_toks)) in enumerate(equations):
            eq_tex = ''.join(repr(c) for c in eq_toks)
            eq_name = 'equation%04d' % i
            # ensure directory exists
            dirname = os.path.join(outdir, eq_name)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
            # write environment name
            fname = os.path.join(outdir, eq_name, 'environment.txt')
            with open(fname, 'w') as f:
                f.write(environment_name)
            # write tex tokens
            fname = os.path.join(outdir, eq_name, 'tokens.json')
            with open(fname, 'w') as f:
                tokens = [dict(type=t.__class__.__name__, value=t.source) for t in eq_toks]
                json.dump(tokens, f)
            # render equation if possible
            if environment_name in ('equation', 'equation*'):
                # make pdf
                fname = os.path.join(outdir, eq_name, 'equation.tex')
                equation = render_equation(eq_tex, template, fname, keep_intermediate)
                if equation is None:
                    # equation couldn't be rendered
                    failed_eqns.append(eq_name)
                    continue
                # find page and aabb where equation appears
                match, p, start, end = match_template(pages, equation, rescale_factor)
                # write image with aabb
                image = pages[p].copy()
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                cv2.rectangle(image, start, end, (0, 0, 255), 2)
                img_name = os.path.join(outdir, eq_name, 'aabb.png')
                cv2.imwrite(img_name, image)
                # write aabb to file (using relative coordinates)
                fname = os.path.join(outdir, eq_name, 'aabb.tsv')
                h, w = image.shape[:2]
                x1 = start[0] / w
                y1 = start[1] / h
                x2 = end[0] / w
                y2 = end[1] / h
                with open(fname, 'w') as f:
                    values = [p, x1, y1, x2, y2]
                    tsv = '\t'.join(map(str, values))
                    print(tsv, file=f)
            else:
                # we skipped bc wasn't an equation environment
                skipped_eqns.append(eq_name)
        # add the failed/skipped eqn info to the log
        if len(failed_eqns) > 0:
            info_log += error_msg(paper_id, 'eqn_failed', failed_eqns)
        if len(skipped_eqns) > 0:
            info_log += error_msg(paper_id, 'eqn_skipped', skipped_eqns)
    else:
        info_log += error_msg(paper_id, 'paper_failed')

    return info_log


if __name__ == '__main__':
    args = parse_args()
    with open(args.logfile, 'w') as logfile:
        for paper_dir in list_paper_dirs(args.indir):
            print('processing', paper_dir, '...')
            try:
                paper_errors = process_paper(paper_dir, args.template, args.outdir, args.rescale_factor, args.dump_pages, args.keep_intermediate_files, args.pdfdir)
            except KeyboardInterrupt:
                raise
            except:
                paper_errors = error_msg(get_paper_id(paper_dir), 'paper_failed')
            # record any errors
            logfile.write(paper_errors)
            logfile.flush()

