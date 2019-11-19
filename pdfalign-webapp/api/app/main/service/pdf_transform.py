import os
import json
import subprocess
from collections import defaultdict
from tkinter import *
from tkinter import ttk
from tkinter.ttk import Button, Frame, Scrollbar, Radiobutton
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from pdf2image import convert_from_path
from lxml import etree
from webcolors import name_to_rgb
from tqdm import tqdm
from aabb_tree import AABB, AABBTree

class PdfAlign(Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master.title("pdfalign")
        self.pack(expand=YES, fill=BOTH)

        self.dpi = 200
        self.scale = 1.0
        self.num_page = 0
        self.num_page_tv = StringVar()
        # bounding boxes
        self.charid = 0
        self.page_boxes = dict(token=[], char=[])
        self.aabb_trees = None
        # The bounding box around the equation to be annotated
        self.annotation_aabb = None
        # Holder to display the transparent rectangles
        self.rectangles = []
        # History
        self.history_boxes = []
        # The lookup for the token that corresponds to the bounding box
        self.all_tokens = []
        self.char_token_lut = dict()
        self.token_char_lut = defaultdict(list)

        # The properties/attributes of the tool itself

        # Annotation colors
        self.annotation_mode = "equation"
        self.active_annotation = None
        self.token_mode = True
        self.ann_mode_index = 0
        self.ann_mode_list = ["eqn", "text", "desc", "unit"]

        toolbar = Frame(self)
        Button(toolbar, text="Open (o)", command=self.open).pack(side=LEFT)
        Button(
            toolbar, text="Import (i)", command=self.import_annotations
        ).pack(side=LEFT)
        Button(toolbar, text="◀", command=self.prev).pack(side=LEFT)
        Button(toolbar, text="▶", command=self.next).pack(side=LEFT)
        Button(toolbar, text="Zoom in (+)", command=self.zoom_in).pack(
            side=LEFT
        )
        Button(toolbar, text="Zoom out (-)", command=self.zoom_out).pack(
            side=LEFT
        )
        ttk.Label(toolbar, textvariable=self.num_page_tv).pack(side=LEFT)

        ttk.Label(toolbar, text="Token mode (k)").pack(side=LEFT)
        self.token_mode_on_rb = Radiobutton(
            toolbar,
            text="on",
            variable=self.token_mode,
            value=True,
            command=self.activate_token_mode,
        )
        self.token_mode_on_rb.pack(side=LEFT)
        self.token_mode_off_rb = Radiobutton(
            toolbar,
            text="Off",
            variable=self.token_mode,
            value=False,
            command=self.deactivate_token_mode,
        )
        self.token_mode_off_rb.pack(side=LEFT)

        Button(
            toolbar,
            text="Annotate new variable (n)",
            command=self.new_annotation,
        ).pack(side=LEFT)
        Button(
            toolbar, text="Add component (a)", command=self.add_component
        ).pack(side=LEFT)
        self.in_equation_rb = Radiobutton(
            toolbar,
            text="In equation (e)",
            value="equation",
            variable=self.annotation_mode,
            command=self.select_equation,
            style="InEquation.TRadiobutton",
        )
        self.in_equation_rb.pack(side=LEFT)
        self.in_text_rb = Radiobutton(
            toolbar,
            text="In text (t)",
            value="text",
            variable=self.annotation_mode,
            command=self.select_text,
            style="InText.TRadiobutton",
        )
        self.in_text_rb.pack(side=LEFT)
        self.description_rb = Radiobutton(
            toolbar,
            text="Description (d)",
            value="description",
            variable=self.annotation_mode,
            command=self.select_description,
            style="Description.TRadiobutton",
        )
        self.description_rb.pack(side=LEFT)
        self.unit_rb = Radiobutton(
            toolbar,
            text="Unit (u)",
            value="unit",
            variable=self.annotation_mode,
            command=self.select_unit,
            style="Unit.TRadiobutton",
        )
        self.unit_rb.pack(side=LEFT)
        Button(toolbar, text="Save (s)", command=self.save_annotation).pack(
            side=LEFT
        )
        Button(
            toolbar, text="Export (x)", command=self.export_annotations
        ).pack(side=LEFT)
        Button(toolbar, text="Quit (q)", command=self.client_exit).pack(
            side=LEFT
        )
        toolbar.pack(side=TOP, fill=BOTH)

        # Keyboard shortcuts
        self.bind_all("o", lambda e: self.open())
        self.bind_all("i", lambda e: self.import_annotations())
        self.bind_all("+", lambda e: self.zoom_in())
        self.bind_all("-", lambda e: self.zoom_out())
        self.bind_all("<Left>", lambda e: self.prev())
        self.bind_all("<Right>", lambda e: self.next())

        self.bind_all("n", lambda e: self.new_annotation())
        self.bind_all("a", lambda e: self.add_component())

        self.bind_all("k", lambda e: self.toggle_boxes())

        self.bind_all("e", lambda e: self.in_equation_rb.invoke())
        self.bind_all("t", lambda e: self.in_text_rb.invoke())
        self.bind_all("d", lambda e: self.description_rb.invoke())
        self.bind_all("u", lambda e: self.unit_rb.invoke())

        self.bind_all("s", lambda e: self.save_annotation())
        self.bind_all("x", lambda e: self.export_annotations())
        self.bind_all("q", lambda e: self.client_exit())
        self.bind_all("<Tab>", lambda e: self.next_mode())

        viewer = Frame(self)

        self.canvas = Canvas(viewer, width=500, height=500)
        viewer_sbarV = Scrollbar(
            viewer, orient=VERTICAL, command=self.canvas.yview
        )
        viewer_sbarH = Scrollbar(
            viewer, orient=HORIZONTAL, command=self.canvas.xview
        )
        viewer_sbarV.pack(side=RIGHT, fill=Y)
        viewer_sbarH.pack(side=BOTTOM, fill=X)
        self.canvas.config(
            yscrollcommand=viewer_sbarV.set, xscrollcommand=viewer_sbarH.set
        )
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.pack(side=LEFT, expand=YES, fill=BOTH)
        viewer.pack(side=LEFT, expand=YES, fill=BOTH)

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        right_side = Frame(self)

        # Saved Annotations List
        history = Frame(right_side)
        history_toolbar = Frame(history)
        # Set exportselection=0 to be able to select things in multiple list
        # boxes without automatically deselecting
        # See: https://stackoverflow.com/a/756875
        self.annotation_list = Listbox(history, exportselection=0)
        hist_sbarV = Scrollbar(
            history, orient=VERTICAL, command=self.annotation_list.yview
        )
        hist_sbarH = Scrollbar(
            history, orient=HORIZONTAL, command=self.annotation_list.xview
        )
        hist_sbarV.pack(side=RIGHT, fill=Y)
        hist_sbarH.pack(side=BOTTOM, fill=X)
        ttk.Label(history, text="Saved Annotations (snippets)").pack(
            side=TOP, fill=X
        )
        self.annotation_list.config(
            yscrollcommand=hist_sbarV.set, xscrollcommand=hist_sbarH.set
        )
        # pack and buttons
        self.annotation_list.pack(side=TOP, fill=BOTH, expand=YES)
        self.annotation_list.bind('<<ListboxSelect>>', lambda e: self.show_annotation())
        Button(
            history_toolbar, text="Edit", command=self.edit_annotation
        ).pack(side=LEFT)
        Button(
            history_toolbar, text="Delete", command=self.delete_annotation
        ).pack(side=LEFT)
        history_toolbar.pack(side=BOTTOM, fill=BOTH)
        history.pack(side=TOP, expand=YES, fill=BOTH)

        annotation_detail = Frame(right_side)

        # equation
        eq_frame = Frame(annotation_detail)
        eq_toolbar = Frame(eq_frame)
        self.equation_list = Listbox(eq_frame, exportselection=0)
        eq_sbarV = Scrollbar(
            eq_frame, orient=VERTICAL, command=self.equation_list.yview
        )
        eq_sbarH = Scrollbar(
            eq_frame, orient=HORIZONTAL, command=self.equation_list.xview
        )
        eq_sbarV.pack(side=RIGHT, fill=Y)
        eq_sbarH.pack(side=BOTTOM, fill=X)
        # Label(
        #     eq_frame,
        #     text="In-Equation Components",
        #     bg=COLOR_DICT["equation"],
        #     fg="white",
        # ).pack(side=TOP, fill=X)
        self.equation_list.config(
            yscrollcommand=eq_sbarV.set,
            xscrollcommand=eq_sbarH.set,
            height=7,
            width=40,
        )
        self.equation_list.pack(side=TOP, fill=X)
        Button(
            eq_toolbar, text="Delete", command=self.delete_equation_component
        ).pack(side=BOTTOM)
        eq_toolbar.pack(side=BOTTOM, fill=BOTH)
        eq_frame.pack(side=TOP, fill=X)

        # text
        text_frame = Frame(annotation_detail)
        text_toolbar = Frame(text_frame)
        self.text_list = Listbox(text_frame, exportselection=0)
        text_sbarV = Scrollbar(
            text_frame, orient=VERTICAL, command=self.text_list.yview
        )
        text_sbarH = Scrollbar(
            text_frame, orient=HORIZONTAL, command=self.text_list.xview
        )
        text_sbarV.pack(side=RIGHT, fill=Y)
        text_sbarH.pack(side=BOTTOM, fill=X)
        # Label(
        #     text_frame,
        #     text="In-Text Components",
        #     bg=COLOR_DICT["text"],
        #     fg="white",
        # ).pack(side=TOP, fill=X)
        self.text_list.config(
            yscrollcommand=text_sbarV.set,
            xscrollcommand=text_sbarH.set,
            height=7,
            width=40,
        )
        self.text_list.pack(side=TOP, fill=X)
        Button(
            text_toolbar, text="Delete", command=self.delete_text_component
        ).pack(side=BOTTOM)
        text_toolbar.pack(side=BOTTOM, fill=BOTH)
        text_frame.pack(side=TOP, fill=X)

        # description
        desc_frame = Frame(annotation_detail)
        desc_toolbar = Frame(desc_frame)
        self.description_list = Listbox(desc_frame, exportselection=0)
        desc_sbarV = Scrollbar(
            desc_frame, orient=VERTICAL, command=self.description_list.yview
        )
        desc_sbarH = Scrollbar(
            desc_frame, orient=HORIZONTAL, command=self.description_list.xview
        )
        desc_sbarV.pack(side=RIGHT, fill=Y)
        desc_sbarH.pack(side=BOTTOM, fill=X)
        # Label(
        #     desc_frame,
        #     text="Description Components",
        #     bg=COLOR_DICT["description"],
        #     fg="white",
        # ).pack(side=TOP, fill=X)
        self.description_list.config(
            yscrollcommand=desc_sbarV.set,
            xscrollcommand=desc_sbarH.set,
            height=7,
            width=40,
        )
        self.description_list.pack(side=TOP, fill=X)
        Button(
            desc_toolbar,
            text="Delete",
            command=self.delete_description_component,
        ).pack(side=BOTTOM)
        desc_toolbar.pack(side=BOTTOM, fill=BOTH)
        desc_frame.pack(side=TOP, fill=X)

        # unit
        unit_frame = Frame(annotation_detail)
        unit_toolbar = Frame(unit_frame)
        self.unit_list = Listbox(unit_frame, exportselection=0)
        unit_sbarV = Scrollbar(
            unit_frame, orient=VERTICAL, command=self.unit_list.yview
        )
        unit_sbarH = Scrollbar(
            unit_frame, orient=HORIZONTAL, command=self.unit_list.xview
        )
        unit_sbarV.pack(side=RIGHT, fill=Y)
        unit_sbarH.pack(side=BOTTOM, fill=X)
        # Label(
        #     unit_frame,
        #     text="Unit Components",
        #     bg=COLOR_DICT["unit"],
        #     fg="white",
        # ).pack(side=TOP, fill=X)
        self.unit_list.config(
            yscrollcommand=unit_sbarV.set,
            xscrollcommand=unit_sbarH.set,
            height=7,
            width=40,
        )
        self.unit_list.pack(side=TOP, fill=BOTH)
        Button(
            unit_toolbar, text="Delete", command=self.delete_unit_component
        ).pack(side=BOTTOM)
        unit_toolbar.pack(side=BOTTOM, fill=X)
        unit_frame.pack(side=TOP, fill=X)

        annotation_detail.pack(side=TOP, fill=X)

        right_side.pack(side=LEFT, fill=BOTH)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(-1 * (event.delta), "units")

    def next_mode(self):
        self.ann_mode_index += 1
        self.ann_mode_index = self.ann_mode_index % len(self.ann_mode_list)
        next_mode = self.ann_mode_list[self.ann_mode_index]
        if next_mode == "eqn":
            self.in_equation_rb.invoke()
        elif next_mode == "text":
            self.in_text_rb.invoke()
        elif next_mode == "desc":
            self.description_rb.invoke()
        elif next_mode == "unit":
            self.unit_rb.invoke()
        else:
            raise ValueError(f"Invalid value for next_mode: {next_mode}")

    def open(self, filename=None):
        if filename is None:
            filename = filedialog.askopenfilename(
                filetypes=[("pdf files", "*.pdf"), ("all files", "*.*")]
            )
        if filename != "":
            self.saved_annotations = []
            self.filename = os.path.abspath(filename)
            print("Converting PDF pages to images...")
            self.pages = convert_from_path(filename, dpi=self.dpi)
            self.populate_bboxes(filename)
            self.aabb_trees = dict(
                token=self.make_trees_from_boxes(self.page_boxes, "token"),
                char=self.make_trees_from_boxes(self.page_boxes, "char"),
            )
            self.num_page = 0

            # Add the box around the equation to annotate
            paper_dir, _ = os.path.split(self.filename)
            aabb_file = os.path.join(paper_dir, "aabb.tsv")
            with open(aabb_file) as aabb:
                line = aabb.readline()
                _, _, eqn_page, xmin, ymin, xmax, ymax = line.strip().split(
                    "\t"
                )
                annotation_aabb = AABB(
                    float(xmin), float(ymin), float(xmax), float(ymax)
                )
                annotation_aabb.page = int(eqn_page)
                self.annotation_aabb = annotation_aabb
            self.num_page = self.annotation_aabb.page
            # self.redraw()

    def client_exit(self):
        already_exported = messagebox.askyesno(
            "pdfalign", "Did you export your annotations?"
        )
        if already_exported:
            exit()
        else:
            messagebox.showinfo(
                "pdfalign", "Click Export to export and then Quit to exit."
            )

    # def get_fill_color(self, box, default_color=None):
    #     if self.active_annotation:
    #         annotation_type = self.active_annotation.get_type(box)
    #         if annotation_type is not None:
    #             return COLOR_DICT[annotation_type]
    #     if default_color is not None:
    #         return COLOR_DICT[default_color]
    #     return ""

    def box_mode(self):
        if self.token_mode == True:
            return "token"
        return "char"

    def mk_rectangle(self, aabb, color, transparency):
        color = name_to_rgb(color) + (transparency,)
        w = int(aabb.width * self.dpi * self.scale)
        h = int(aabb.height * self.dpi * self.scale)
        img = Image.new("RGBA", (w, h), color)
        rectangle = ImageTk.PhotoImage(img)
        self.rectangles.append(rectangle)
        return rectangle

    # def redraw(self):
    #     self.canvas.delete("all")
    #     page = self.pages[self.num_page]
    #     (page_w, page_h) = page.size
    #     if self.scale != 1:
    #         size = (int(page_w * self.scale), int(page_h * self.scale))
    #         page = page.resize(size, Image.ANTIALIAS)
    #     self.image = ImageTk.PhotoImage(page)
    #     tag = self.canvas.create_image(0, 0, image=self.image, anchor=NW)
    #     # Iterate through the bounding boxes to display them as needed
    #     for box_mode in ["token", "char"]:
    #         for box in self.page_boxes[box_mode][self.num_page]:
    #             xmin = box.xmin * self.scale * self.dpi
    #             ymin = box.ymin * self.scale * self.dpi
    #             xmax = box.xmax * self.scale * self.dpi
    #             ymax = box.ymax * self.scale * self.dpi
    #             active_color = COLOR_DICT[self.annotation_mode]
    #             # if it's in the annotations, make a rectangle, color defined by annotation type
    #             box_type = None
    #             transparency = 0
    #             for saved_annotation in self.saved_annotations:
    #                 box_type = saved_annotation.get_type(box)
    #                 if box_type is not None:
    #                     transparency = 25
    #                     break
    #             if self.active_annotation is not None:
    #                 curr_annotation_box_type = self.active_annotation.get_type(
    #                     box
    #                 )
    #                 if curr_annotation_box_type is not None:
    #                     box_type = curr_annotation_box_type
    #                     if self.active_annotation.is_active_component(box):
    #                         transparency = 150
    #                     else:
    #                         transparency = 60
    #             if box_type is not None:
    #                 rect = self.mk_rectangle(
    #                     box, COLOR_DICT[box_type], transparency
    #                 )
    #                 self.canvas.create_image(xmin, ymin, image=rect, anchor=NW)
    #             # else mk rectangle with outline so we still have the hover
    #             # here only show the outlines of the boxes that correspond to our current view mode (token/char)
    #             else:
    #                 if self.box_mode() == box_mode:
    #                     self.canvas.create_rectangle(
    #                         xmin,
    #                         ymin,
    #                         xmax,
    #                         ymax,
    #                         outline=self.get_fill_color(
    #                             box, default_color="unselected"
    #                         ),
    #                         activeoutline=active_color,
    #                         fill="",
    #                     )
    #     self.canvas.tag_lower(tag)
    #
    #     if self.num_page == self.annotation_aabb.page:
    #         # draw the bounding box for the equation to be annotated
    #         xmin = self.annotation_aabb.xmin * self.scale * page_w
    #         ymin = self.annotation_aabb.ymin * self.scale * page_h
    #         xmax = self.annotation_aabb.xmax * self.scale * page_w
    #         ymax = self.annotation_aabb.ymax * self.scale * page_h
    #         self.canvas.create_rectangle(
    #             xmin, ymin, xmax, ymax, outline="firebrick", fill="", width=2
    #         )
    #
    #     self.update()
    #     self.canvas.config(scrollregion=self.canvas.bbox(ALL))
    #     self.num_page_tv.set(f"{self.num_page+1}/{len(self.pages)}")

    def get_mode_tv(self):
        if self.annotation_mode == "equation":
            return "IN_EQN"
        elif self.annotation_mode == "text":
            return "IN_TEXT"
        elif self.annotation_mode == "description":
            return "DESCRIPTION"
        elif self.annotation_mode == "unit":
            return "UNIT"
        else:
            return "N/A"

    def prev(self):
        self.num_page -= 1
        if self.num_page < 0:
            self.num_page = 0
        self.redraw()

    def next(self):
        self.num_page += 1
        if self.num_page >= len(self.pages):
            self.num_page = len(self.pages) - 1
        self.redraw()

    def zoom_in(self):
        self.scale *= 2
        if self.scale > 2.0:
            self.scale = 2.0
        self.redraw()

    def zoom_out(self):
        self.scale /= 2
        if self.scale < 0.2:
            self.scale = 0.2
        self.redraw()

    def click(self, event):
        canvas = event.widget
        # Normalize coordinates
        x = canvas.canvasx(event.x) / self.scale / self.dpi
        y = canvas.canvasy(event.y) / self.scale / self.dpi
        # Query synctex
        result = synctex(self.num_page, x, y, self.filename)

        # Get annotation
        if self.active_annotation and self.annotation_mode:
            tree = self.aabb_trees[self.box_mode()][self.num_page]
            collisions = tree.contains(Point(x, y))
            for b in collisions:
                b.synctex = result
                self.console_display(b)
            self.active_annotation.toggle_annotations(
                self.annotation_mode, collisions
            )
            self.redraw()

    def console_display(self, box):
        if box.token is not None:
            token = box.token
        else:
            token = box.value
        print(
            f"value: {box.value}\ttoken: {token}\tfont: {box.font}\tfont_size: {box.font_size}"
        )

    # ---------------------------------------
    #          Annotating
    # ---------------------------------------

    def new_annotation(self):
        self.maybe_save_unsaved()
        self.active_annotation = Annotation()
        self.in_equation_rb.invoke()
        self.redraw()

    def select_equation(self):
        if self.active_annotation is not None:
            self.annotation_mode = "equation"
            self.token_mode = False
            self.redraw()

    def select_text(self):
        if self.active_annotation is not None:
            self.annotation_mode = "text"
            self.token_mode = True
            self.redraw()

    def select_description(self):
        if self.active_annotation is not None:
            self.annotation_mode = "description"
            self.token_mode = True
            self.redraw()

    def select_unit(self):
        if self.active_annotation is not None:
            self.annotation_mode = "unit"
            self.token_mode = True
            self.redraw()

    def add_component(self):
        if self.active_annotation is None:
            messagebox.showinfo(
                "pdfalign",
                "You don't have an active annotation. Please add new.",
            )
            return
        self.active_annotation.add_component(self.annotation_mode)
        self.redraw()

    def toggle_boxes(self):
        if self.token_mode:
            self.token_mode_off_rb.invoke()
        else:
            self.token_mode_on_rb.invoke()
        self.redraw()

    def activate_token_mode(self):
        self.token_mode = True
        self.redraw()

    def deactivate_token_mode(self):
        self.token_mode = False
        self.redraw()

    # ---------------------------------------
    #         Show details
    # ---------------------------------------

    def show_annotation(self):
        selected = self.annotation_list.curselection()
        if len(selected) == 0:
            return
        # clear out prev shown annotation
        if (
            self.equation_list.size() > 0
            or self.text_list.size() > 0
            or self.description_list.size() > 0
            or self.unit_list.size() > 0
        ):
            self.equation_list.delete(0, END)
            self.text_list.delete(0, END)
            self.description_list.delete(0, END)
            self.unit_list.delete(0, END)
        selected = self.annotation_list.curselection()
        if len(selected) == 0:
            return
        selected = self.saved_annotations[selected[0]]
        self.maybe_save_unsaved()
        # update the annotation_detail panels
        [
            self.equation_list.insert(END, selected.boxes_summary([eq]))
            for eq in selected.equation
        ]
        [
            self.text_list.insert(END, selected.boxes_summary([txt]))
            for txt in selected.text
        ]
        [
            self.description_list.insert(END, selected.boxes_summary([desc]))
            for desc in selected.description
        ]
        [
            self.unit_list.insert(END, selected.boxes_summary([un]))
            for un in selected.unit
        ]
        # redraw
        self.redraw()

    # ---------------------------------------
    #         Editing and Deleting
    # ---------------------------------------

    def edit_annotation(self):
        selected = self.annotation_list.curselection()
        if len(selected) == 0:
            return
        selected = selected[0]
        self.maybe_save_unsaved()
        # check that there are the proper selections
        valid_equation = self.check_selection("equation")
        valid_text = self.check_selection("text")
        valid_description = self.check_selection("description")
        valid_unit = self.check_selection("unit")
        if (
            not valid_equation
            or not valid_text
            or not valid_description
            or not valid_unit
        ):
            messagebox.showinfo(
                "pdfalign",
                "Sorry, you must select components to edit annotation.",
            )
            return
        # get the previous annotation
        self.active_annotation = self.saved_annotations[selected]
        # remove it so we don't have 2 copies
        del self.saved_annotations[selected]
        self.annotation_list.delete(selected)
        # activate the components selected in the annotation_detail panels
        self.active_annotation.activate_component(
            "equation", self.equation_list.curselection()
        )
        self.active_annotation.activate_component(
            "text", self.text_list.curselection()
        )
        self.active_annotation.activate_component(
            "description", self.description_list.curselection()
        )
        self.active_annotation.activate_component(
            "unit", self.unit_list.curselection()
        )
        self.redraw()

    def delete_annotation(self):
        selected = self.annotation_list.curselection()
        if len(selected) == 0:
            return
        really_delete = messagebox.askokcancel(
            "pdfalign",
            "Are you sure you want to delete the selected annotation?",
        )
        if really_delete:
            selected = selected[0]
            del self.saved_annotations[selected]
            self.annotation_list.delete(selected)
            self.redraw()

    def delete_equation_component(self):
        if self.active_annotation is None:
            messagebox.showinfo("pdfalign", "You need to click edit first.")
            return
        selected = self.equation_list.curselection()
        if len(selected) == 0:
            print("nothing selected")
            return
        # check that they're sure
        really_delete = messagebox.askokcancel(
            "pdfalign",
            "Are you sure you want to delete the selected component?",
        )
        if really_delete:
            # if you've just deleted something, add the selected to the active
            if len(self.active_annotation.active_equation) == 0:
                self.active_annotation.activate_component("equation", selected)
            # remove the selected component from the annotation
            selected = selected[0]
            self.active_annotation.active_equation = set()
            self.equation_list.delete(selected)
            self.redraw()

    def delete_text_component(self):
        if self.active_annotation is None:
            messagebox.showinfo("pdfalign", "You need to click edit first.")
            return
        selected = self.text_list.curselection()
        if len(selected) == 0:
            print("nothing selected")
            return
        # check that they're sure
        really_delete = messagebox.askokcancel(
            "pdfalign",
            "Are you sure you want to delete the selected component?",
        )
        if really_delete:
            # if you've just deleted something, add the selected to the active
            if len(self.active_annotation.active_text) == 0:
                self.active_annotation.activate_component("text", selected)
            # remove the selected component from the annotation
            selected = selected[0]
            self.active_annotation.active_text = set()
            self.text_list.delete(selected)
            self.redraw()

    def delete_description_component(self):
        if self.active_annotation is None:
            messagebox.showinfo("pdfalign", "You need to click edit first.")
            return
        selected = self.description_list.curselection()
        if len(selected) == 0:
            print("nothing selected")
            return
        # check that they're sure
        really_delete = messagebox.askokcancel(
            "pdfalign",
            "Are you sure you want to delete the selected component?",
        )
        if really_delete:
            # if you've just deleted something, add the selected to the active
            if len(self.active_annotation.active_description) == 0:
                self.active_annotation.activate_component(
                    "description", selected
                )
            # remove the selected component from the annotation
            selected = selected[0]
            self.active_annotation.active_description = set()
            self.description_list.delete(selected)
            self.redraw()

    def delete_unit_component(self):
        if self.active_annotation is None:
            messagebox.showinfo("pdfalign", "You need to click edit first.")
            return
        selected = self.unit_list.curselection()
        if len(selected) == 0:
            print("nothing selected")
            return
        # check that they're sure
        really_delete = messagebox.askokcancel(
            "pdfalign",
            "Are you sure you want to delete the selected component?",
        )
        if really_delete:
            # if you've just deleted something, add the selected to the active
            if len(self.active_annotation.active_unit) == 0:
                self.active_annotation.activate_component("unit", selected)
            # remove the selected component from the annotation
            selected = selected[0]
            self.active_annotation.active_unit = set()
            self.unit_list.delete(selected)
            self.redraw()

    # ---------------------------------------
    #         Saving and Exporting
    # ---------------------------------------

    def save_annotation(self):
        if self.active_annotation is not None:
            self.active_annotation.save_components()
            annotation = self.active_annotation
            self.saved_annotations.append(annotation)
            self.annotation_list.insert(END, annotation.snippet())
            self.active_annotation = None
            self.in_equation_rb.invoke()
            # remove shown components from the annotation details list
            self.equation_list.delete(0, END)
            self.text_list.delete(0, END)
            self.description_list.delete(0, END)
            self.unit_list.delete(0, END)
            self.redraw()

    def export_annotations(self):
        self.maybe_save_unsaved()
        initialdir, _ = os.path.split(self.filename)
        _, paperdir = os.path.split(initialdir)
        suggested_filename = paperdir + ".json"
        f = filedialog.asksaveasfile(
            filetypes=[("json files", "*.json"), ("all files", "*.*")],
            initialdir=initialdir,
            initialfile=suggested_filename,
        )
        if f is not None:
            annotations = [
                a.serialize(self.token_char_lut, self.all_tokens)
                for a in self.saved_annotations
            ]
            json.dump(annotations, f, indent=4, ensure_ascii=False)
            f.close()
        # FIXME: buggy on mac -- doesn't always close...?

    def import_annotations(self):
        # Warn if there are unsaved annotations
        really_import = True
        if (
            len(self.saved_annotations) > 0
            or self.active_annotation is not None
        ):
            really_import = messagebox.askokcancel(
                "pdfalign",
                "You have existing annotations that will be lost.  Do you want to continue with the import?",
            )
        if really_import:
            # Clear all
            self.saved_annotations = []
            self.active_annotation = None
            self.annotation_list.delete(0, END)
            self.equation_list.delete(0, END)
            self.text_list.delete(0, END)
            self.description_list.delete(0, END)
            self.unit_list.delete(0, END)
            # Import
            filename = filedialog.askopenfilename(
                filetypes=[("json files", "*.json"), ("all files", "*.*")]
            )
            if filename != "":
                with open(filename) as js:
                    json_annotations = json.load(js)
                    # FIXME : recreate all_tokens and the luts
                    for a in json_annotations:
                        annotation = self.deserialize_annotation(a)
                        # Add the annotations to the saved annotations
                        self.saved_annotations.append(annotation)
                        self.annotation_list.insert(END, annotation.snippet())

            self.redraw()

    def deserialize_annotation(self, d):
        a = Annotation()
        a.equation = a.deserialize_boxes(d.get("equation"))
        a.text = a.deserialize_boxes(d.get("text"))
        a.description = a.deserialize_boxes(d.get("description"))
        a.unit = a.deserialize_boxes(d.get("unit"))
        return a

    # ---------------------------------------
    #         Bounding Box Methods
    # ---------------------------------------
    # NOTE pdftotext -bbox-layout returns the bounding boxes of the first page only
    # so we need to split the paper into pages and call this for each page

    def populate_page_bboxes(self, filename, page):
        dpi = 72  # educated guess
        command = ["pdf2txt.py", "-t", "xml", filename]
        result = subprocess.run(command, capture_output=True)
        x = remove_bad_chars(result.stdout)
        tree = etree.fromstring(x)
        page_height = None
        curr_token_aabb = None
        char_boxes = []
        token_boxes = []

        for node in tree.findall(".//page"):
            page_height = float(node.attrib["bbox"].split(",")[3])
        # .//text
        for node in tree.findall(".//text"):
            text = node.text
            if text is not None:
                if len(text.strip()) == 0 and curr_token_aabb is not None:
                    # The current token ended
                    curr_token_aabb.page = page
                    curr_token_aabb.id = len(self.all_tokens)
                    self.all_tokens.append(curr_token_aabb)
                    token_boxes.append(curr_token_aabb)
                    curr_token_aabb = None

                else:
                    # "576.926,76.722,581.357,86.733"
                    bbox = node.attrib.get("bbox")
                    if bbox is not None:
                        # The bboxes from pdf2txt are a little diff:
                        # per https://github.com/euske/pdfminer/issues/171
                        # The bbox value is (x0,y0,x1,y1).
                        # x0: the distance from the left of the page to the left edge of the box.
                        # y0: the distance from the bottom of the page to the lower edge of the box.
                        # x1: the distance from the left of the page to the right edge of the box.
                        # y1: the distance from the bottom of the page to the upper edge of the box.
                        # so here we flip the ys
                        xmin, ymax, xmax, ymin = [
                            float(x) for x in bbox.split(",")
                        ]
                        xmin /= dpi
                        ymin = (page_height - ymin) / dpi
                        xmax /= dpi
                        ymax = (page_height - ymax) / dpi
                        aabb = AABB(xmin, ymin, xmax, ymax)
                        # Store metadata
                        aabb.value = text
                        aabb.page = page
                        aabb.font = node.attrib.get("font")
                        aabb.font_size = node.attrib.get("size")
                        # Token info
                        if curr_token_aabb is None:
                            curr_token_aabb = AABB(xmin, ymin, xmax, ymax)
                            curr_token_aabb.value = text
                        else:
                            new_value = curr_token_aabb.value + text
                            curr_token_aabb = AABB.merge(curr_token_aabb, aabb)
                            curr_token_aabb.value = new_value
                        aabb.tokenid = len(self.all_tokens)
                        aabb.id = self.charid
                        self.charid += 1
                        # Update the bbox luts
                        self.char_token_lut[aabb] = aabb.tokenid
                        self.token_char_lut[aabb.tokenid].append(aabb)
                        # Add the current box
                        char_boxes.append(aabb)
        self.page_boxes["token"].append(token_boxes)
        self.page_boxes["char"].append(char_boxes)

    def populate_bboxes(self, filename):
        for i, p in enumerate(
            tqdm(
                split_pages(filename),
                desc="Populating page bboxes",
                unit="page",
                ncols=80,
            )
        ):
            self.populate_page_bboxes(p, i)
        for page in self.page_boxes["char"]:
            for box in page:
                box.token = self.all_tokens[box.tokenid].value

    def make_trees_from_boxes(self, page_boxes, box_type):
        return [
            AABBTree.from_boxes(page)
            for page in tqdm(
                page_boxes[box_type],
                desc=f"Making binary trees from {box_type} boxes",
                unit="page",
                ncols=80,
            )
        ]

    # ---------------------------------------
    #                Utils
    # ---------------------------------------

    def maybe_save_unsaved(self):
        if self.active_annotation is not None:
            # warn the user that they have unsaved annotations
            save_unsaved = messagebox.askyesno(
                "pdfalign",
                "You have unsaved annotations which will be lost, would you like to save them first?",
            )
            if save_unsaved:
                self.save_annotation()

    # There is either something selected or nothing to select
    def check_selection(self, component_type):
        listbox = getattr(self, f"{component_type}_list")
        selected = listbox.curselection()
        return len(selected) > 0 or listbox.size() == 0

def split_pages(filename):
    print(f"Separating pages for file {filename}")
    dirname = os.path.dirname(filename)
    page_pattern = os.path.join(dirname, "page-%03d.pdf")
    command = ["pdfseparate", filename, page_pattern]
    subprocess.run(command)
    pages = [
        os.path.join(dirname, f)
        for f in os.listdir(dirname)
        if re.search(r"page-\d+\.pdf$", f)
    ]
    return sorted(pages)

def remove_bad_chars(text):
    # NOTE 9 (tab), 10 (line feed), and 13 (carriage return) are not bad
    bad_codes = [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        11,
        12,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
    ]
    bad_chars = [chr(c) for c in bad_codes]
    bad_bytes = [bytes([c]) for c in bad_codes]
    if isinstance(text, bytes):
        for byte in bad_bytes:
            text = text.replace(byte, b"")
    elif isinstance(text, str):
        for char in bad_chars:
            text = text.replace(char, "")
    return text


def main():
    temp = PdfAlign()
    temp.open("../resources/temp.pdf")

main()
