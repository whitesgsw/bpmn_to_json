#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BPMN Studio

Tool is used to structure BPMN diagrams into JSON objects ready to be consumed by LLM models.
The purpose of this tool is to be able to model BPMN in graphical interface as well as a JSON
structure and convert between formats.
Converting the base XML structure to JSON increases the likelihood of correct LLM interpretation
and decreases the token count compared to raw XML.
The tool also supports exporting to BPMN XML format for compatibility with other BPMN tools.

Run:
  python bpmn_studio.py
"""
import copy
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, colorchooser
import xml.etree.ElementTree as ET

# Optional PNG export via Pillow.
# NOTE: converting PostScript -> PNG also requires Ghostscript to be installed on the system.
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ----------------------------- Data Model ------------------------------------
class Node:
    def __init__(self, nid, ntype, x, y, w=120, h=60, text=None, lane_id=None,
                 fill=None, outline=None, text_color=None):
        self.id = nid
        self.type = ntype  # 'startEvent' | 'endEvent' | 'task' | 'exclusiveGateway' |
                           # 'parallelGateway' | 'inclusiveGateway' | 'intermediateEvent' |
                           # 'lane' | 'pool'
        self.subtype = None  # original BPMN task tag (e.g. 'userTask', 'serviceTask', 'scriptTask')
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.text = text or ntype
        self.lane_id = lane_id
        self.fill = fill
        self.outline = outline
        self.text_color = text_color
        self.incoming = []
        self.outgoing = []
        self.next = []
        self.prev = []

    def ensure_defaults_for_type(self):
        if self.type == "pool":
            self.fill = self.fill or "#f8fafc"
            self.outline = self.outline or "#94a3b8"
            self.text_color = self.text_color or "#111827"
        elif self.type == "lane":
            self.fill = self.fill or "#f9fbff"
            self.outline = self.outline or "#b9c6d3"
            self.text_color = self.text_color or "#111827"
        elif self.type == "task":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#374151"
            self.text_color = self.text_color or "#111827"
        elif self.type == "startEvent":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#3b82f6"
            self.text_color = self.text_color or "#111827"
        elif self.type == "endEvent":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#ef4444"
            self.text_color = self.text_color or "#111827"
        elif self.type == "exclusiveGateway":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#ef4444"
            self.text_color = self.text_color or "#ef4444"
        elif self.type == "parallelGateway":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#3b82f6"
            self.text_color = self.text_color or "#3b82f6"
        elif self.type == "inclusiveGateway":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#f59e0b"
            self.text_color = self.text_color or "#f59e0b"
        elif self.type == "intermediateEvent":
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#f59e0b"
            self.text_color = self.text_color or "#111827"
        else:
            self.fill = self.fill or "#ffffff"
            self.outline = self.outline or "#111827"
            self.text_color = self.text_color or "#111827"

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "subtype": self.subtype,
            "name": self.text,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "lane": self.lane_id,
            "incoming": self.incoming,
            "outgoing": self.outgoing,
            "next": self.next,
            "prev": self.prev,
            "style": {"fill": self.fill, "outline": self.outline, "text": self.text_color},
        }


class Edge:
    def __init__(self, eid, src, tgt, label=None, etype="sequenceFlow"):
        self.id = eid
        self.type = etype  # 'sequenceFlow' | 'messageFlow' | 'association'
        self.src = src
        self.tgt = tgt
        self.name = label or ""
        self.condition = None

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "from": self.src,
            "to": self.tgt,
            "name": self.name,
            "condition": self.condition,
        }


# Maps internal node type to the prefix used when auto-generating IDs.
_TYPE_PREFIX = {
    "startEvent": "StartEvent",
    "endEvent": "EndEvent",
    "task": "Task",
    "exclusiveGateway": "ExclusiveGateway",
    "parallelGateway": "ParallelGateway",
    "inclusiveGateway": "InclusiveGateway",
    "intermediateEvent": "IntermediateEvent",
    "lane": "Lane",
    "pool": "Pool",
}


class BPMNModel:
    def __init__(self, process_name="Process_1"):
        self.process_name = process_name
        self.nodes = {}
        self.edges = []
        self._counter = 1

    def gen_id(self, prefix):
        nid = f"{prefix}_{self._counter}"
        self._counter += 1
        return nid

    def add_node(self, ntype, x, y):
        if ntype == "lane":
            w, h = 900, 150
            text = "Lane"
        elif ntype == "startEvent":
            w, h = 60, 60
            text = "Start"
        elif ntype == "endEvent":
            w, h = 60, 60
            text = "End"
        elif ntype == "exclusiveGateway":
            w, h = 80, 80
            text = "XOR"
        elif ntype == "parallelGateway":
            w, h = 80, 80
            text = "AND"
        elif ntype == "inclusiveGateway":
            w, h = 80, 80
            text = "OR"
        elif ntype == "intermediateEvent":
            w, h = 60, 60
            text = "Event"
        elif ntype == "pool":
            w, h = 1100, 220
            text = "Pool"
        else:
            w, h = 160, 80
            text = "Task"
        prefix = _TYPE_PREFIX.get(ntype, ntype)
        nid = self.gen_id(prefix)
        node = Node(nid, ntype, x, y, w, h, text=text)
        node.ensure_defaults_for_type()
        self.nodes[nid] = node
        return node

    def add_node_with_id(self, nid, ntype, x, y, w, h, text,
                          fill=None, outline=None, text_color=None):
        node = Node(nid, ntype, x, y, w, h, text=text,
                    fill=fill, outline=outline, text_color=text_color)
        node.ensure_defaults_for_type()
        self.nodes[nid] = node
        return node

    def _link_edge(self, edge):
        """Update node incoming/outgoing/next/prev lists for a sequenceFlow edge."""
        if edge.type != "sequenceFlow":
            return
        if edge.src in self.nodes:
            self.nodes[edge.src].outgoing.append(edge.id)
            self.nodes[edge.src].next.append(edge.tgt)
        if edge.tgt in self.nodes:
            self.nodes[edge.tgt].incoming.append(edge.id)
            self.nodes[edge.tgt].prev.append(edge.src)

    def add_edge(self, src_id, tgt_id, label="", etype="sequenceFlow"):
        prefix = "Flow" if etype == "sequenceFlow" else etype
        eid = self.gen_id(prefix)
        return self.add_edge_with_id(eid, src_id, tgt_id, label, etype)

    def add_edge_with_id(self, eid, src_id, tgt_id, label="", etype="sequenceFlow"):
        edge = Edge(eid, src_id, tgt_id, label, etype=etype)
        self.edges.append(edge)
        self._link_edge(edge)
        return edge

    def delete_node(self, nid):
        if nid not in self.nodes:
            return
        to_remove = [e for e in self.edges if e.src == nid or e.tgt == nid]
        for e in to_remove:
            self.delete_edge(e.id)
        del self.nodes[nid]

    def delete_edge(self, eid):
        kept = []
        target = None
        for e in self.edges:
            if e.id == eid:
                target = e
            else:
                kept.append(e)
        if target and target.type == "sequenceFlow":
            if target.src in self.nodes:
                n = self.nodes[target.src]
                n.outgoing = [i for i in n.outgoing if i != eid]
                n.next = [t for t in n.next if t != target.tgt]
            if target.tgt in self.nodes:
                n = self.nodes[target.tgt]
                n.incoming = [i for i in n.incoming if i != eid]
                n.prev = [p for p in n.prev if p != target.src]
        self.edges = kept

    def to_json(self):
        return {
            "definitions_id": "Defs_1",
            "processes": [{
                "id": "Process_1",
                "name": self.process_name,
                "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
                "edges": [e.to_dict() for e in self.edges],
                "di": {"shapes": {}, "edges": {}},
            }],
            "collaboration": {"messageFlows": []},
        }

    def load_json(self, data):
        self.nodes.clear()
        self.edges.clear()
        self._counter = 1
        procs = data.get("processes", [])
        if not procs:
            return
        p = procs[0]
        self.process_name = p.get("name") or "Process_1"
        for nid, nd in p.get("nodes", {}).items():
            style = nd.get("style", {}) or {}
            node = Node(
                nid, nd.get("type"), nd.get("x"), nd.get("y"),
                nd.get("w", 120), nd.get("h", 60),
                text=(nd.get("name") or nd.get("type") or "Node"),
                lane_id=nd.get("lane"),
                fill=style.get("fill"), outline=style.get("outline"), text_color=style.get("text"),
            )
            node.subtype = nd.get("subtype")
            node.ensure_defaults_for_type()
            node.incoming = [str(x) for x in (nd.get("incoming", []) or []) if x is not None]
            node.outgoing = [str(x) for x in (nd.get("outgoing", []) or []) if x is not None]
            node.next = [str(x) for x in (nd.get("next", []) or []) if x is not None]
            node.prev = [str(x) for x in (nd.get("prev", []) or []) if x is not None]
            self.nodes[nid] = node
        for ed in p.get("edges", []):
            e = Edge(ed.get("id"), ed.get("from"), ed.get("to"), ed.get("name"),
                     etype=ed.get("type", "sequenceFlow"))
            e.condition = ed.get("condition")
            self.edges.append(e)
        # Set counter above the highest numeric suffix in all existing IDs to prevent collisions.
        max_num = 0
        all_ids = list(self.nodes.keys()) + [e.id for e in self.edges if e.id]
        for id_str in all_ids:
            parts = id_str.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                max_num = max(max_num, int(parts[1]))
        self._counter = max_num + 1


# ----------------------------- GUI / Controller ------------------------------
class BPMNStudio(tk.Tk):
    BG = "#f4f5f7"
    GRID = 10
    NS = {
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
    }

    def q(self, tag, ns="bpmn"):
        return f"{{{self.NS[ns]}}}{tag}"

    def __init__(self):
        super().__init__()
        self.title("BPMN Studio")
        self.geometry("1400x860")
        self.configure(bg=self.BG)

        self.model = BPMNModel()
        self.current_file = None
        self.view_mode = "bpmn"
        self._dirty = False
        self._current_tool = tk.StringVar(value="select")

        # Zoom
        self._zoom = 1.0

        # Snap to grid
        self._snap_to_grid = True
        self._snap_var = tk.BooleanVar(value=True)

        # Selection/drag state
        self._selected_item = None
        self._selected_type = None
        self._node_by_item = {}
        self._edge_by_item = {}
        self._label_by_item = {}
        self._drag_offset = (0, 0)
        self._connect_source = None
        self._active_lane_id = None
        self._lane_handle_to_info = {}
        self._resizing_lane = None
        self._dragging_lane = None

        # Multi-select state
        self._multi_select = set()
        self._rubber_band_start = None
        self._rubber_band_item = None
        self._primary_drag_nid = None

        # Copy/paste clipboard
        self._clipboard = []

        # Properties panel state
        self._prop_updating = False
        self._prop_name_var = tk.StringVar()
        self._prop_cond_var = tk.StringVar()

        # Undo/Redo
        self._history = []
        self._redo = []
        self._max_history = 15
        self._changed_during_drag = False

        # Grid debounce
        self._grid_after_id = None

        # Build UI
        self._build_menu()
        self._build_left_toolbar()
        self._build_main_area()
        self._build_properties_panel()
        self._bind_canvas_events()
        self._bind_pan_keys()
        self._bind_mouse_wheel()
        self._bind_keyboard_shortcuts()

        # Context menu
        self._ctx_menu = tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="Delete", command=self.ctx_delete)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="Bring forward", command=self.ctx_bring_forward)
        self._ctx_menu.add_command(label="Send backward", command=self.ctx_send_backward)
        self._ctx_menu.add_separator()
        # Colour cascade submenu for nodes
        self._colour_menu = tk.Menu(self._ctx_menu, tearoff=0)
        self._colour_menu.add_command(label="Fill Colour…",
                                      command=lambda: self._pick_colour("fill"))
        self._colour_menu.add_command(label="Outline Colour…",
                                      command=lambda: self._pick_colour("outline"))
        self._colour_menu.add_command(label="Text Colour…",
                                      command=lambda: self._pick_colour("text_color"))
        self._ctx_menu.add_cascade(label="Change Colour…", menu=self._colour_menu)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Control-Button-1>", self.on_right_click)  # macOS Ctrl+Click

        # Global shortcuts (Undo/Redo/Copy/Paste)
        self.bind_all("<Control-z>", lambda e: self.cmd_undo())
        self.bind_all("<Control-y>", lambda e: self.cmd_redo())
        self.bind_all("<Command-z>", lambda e: self.cmd_undo())
        self.bind_all("<Command-Shift-Z>", lambda e: self.cmd_redo())
        self.bind_all("<Control-c>", lambda e: self.cmd_copy())
        self.bind_all("<Control-v>", lambda e: self.cmd_paste())
        self.bind_all("<Control-a>", lambda e: self.cmd_select_all())

        self._update_window_title()
        self._push_history("init")

    # -------- Zoom helpers
    def _mc(self, v):
        """Convert model coordinate to canvas coordinate."""
        return v * self._zoom

    def _cm(self, v):
        """Convert canvas coordinate to model coordinate."""
        return v / self._zoom

    def zoom_in(self):
        self._zoom = min(4.0, self._zoom * 1.25)
        self.redraw_all()

    def zoom_out(self):
        self._zoom = max(0.25, self._zoom / 1.25)
        self.redraw_all()

    def zoom_reset(self):
        self._zoom = 1.0
        self.redraw_all()

    # -------- UI builders
    def _build_menu(self):
        self.menubar = tk.Menu(self)
        fm = tk.Menu(self.menubar, tearoff=0)
        fm.add_command(label="New", command=self.new_diagram)
        fm.add_command(label="Open JSON…", command=self.open_json)
        fm.add_command(label="Open BPMN XML…", command=self.open_bpmn)
        fm.add_command(label="Save", command=self.save_file)
        fm.add_command(label="Save As…", command=self.save_json_as)
        fm.add_separator()
        fm.add_command(label="Export BPMN XML…", command=self.export_bpmn)
        fm.add_command(label="Export PNG…", command=self.export_png)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.destroy)
        self.menubar.add_cascade(label="File", menu=fm)

        em = tk.Menu(self.menubar, tearoff=0)
        em.add_command(label="Copy", command=self.cmd_copy)
        em.add_command(label="Paste", command=self.cmd_paste)
        em.add_command(label="Select All", command=self.cmd_select_all)
        em.add_separator()
        em.add_command(label="Auto Layout", command=self.auto_layout)
        em.add_separator()
        em.add_command(label="Validate", command=self.validate_diagram)
        self.menubar.add_cascade(label="Edit", menu=em)

        vm = tk.Menu(self.menubar, tearoff=0)
        vm.add_command(label="BPMN View", command=self.toggle_view_bpmn)
        vm.add_command(label="JSON View", command=self.toggle_view_json)
        vm.add_separator()
        vm.add_command(label="Zoom In", command=self.zoom_in)
        vm.add_command(label="Zoom Out", command=self.zoom_out)
        vm.add_command(label="Reset Zoom", command=self.zoom_reset)
        self.menubar.add_cascade(label="View", menu=vm)
        self.config(menu=self.menubar)

    def _build_left_toolbar(self):
        self.toolbar = tk.Frame(self, bg="#ffffff", padx=8, pady=8)

        def add_btn(lbl, tool, shortcut=None):
            display = f"{lbl}  [{shortcut}]" if shortcut else lbl
            b = tk.Radiobutton(self.toolbar, text=display, indicatoron=False, width=20,
                               value=tool, variable=self._current_tool)
            b.pack(pady=3, anchor="n", fill="x")

        add_btn("Select/Move", "select", "s")
        tk.Label(self.toolbar, text="Add:", bg="#ffffff", anchor="w").pack(fill="x", pady=(12, 2))
        add_btn("Start Event", "startEvent", "b")
        add_btn("End Event", "endEvent", "e")
        add_btn("Task", "task", "t")
        add_btn("Exclusive Gateway", "exclusiveGateway", "x")
        add_btn("Parallel Gateway", "parallelGateway", "p")
        add_btn("Inclusive Gateway", "inclusiveGateway", "i")
        add_btn("Intermediate Event", "intermediateEvent", "m")
        add_btn("Swimlane", "lane", "l")
        add_btn("Pool", "pool", "o")
        tk.Label(self.toolbar, text="Connect:", bg="#ffffff", anchor="w").pack(fill="x", pady=(12, 2))
        add_btn("Sequence Flow", "connector", "c")
        add_btn("Message Flow", "msgConnector", "f")

        tk.Label(self.toolbar, text="Zoom:", bg="#ffffff", anchor="w").pack(fill="x", pady=(12, 2))
        zoom_frame = tk.Frame(self.toolbar, bg="#ffffff")
        zoom_frame.pack(fill="x", pady=2)
        tk.Button(zoom_frame, text="+", width=4, command=self.zoom_in).pack(side=tk.LEFT, padx=1)
        tk.Button(zoom_frame, text="−", width=4, command=self.zoom_out).pack(side=tk.LEFT, padx=1)
        tk.Button(zoom_frame, text="100%", width=5, command=self.zoom_reset).pack(side=tk.LEFT, padx=1)

        tk.Label(self.toolbar, text="Options:", bg="#ffffff", anchor="w").pack(fill="x", pady=(12, 2))
        snap_cb = tk.Checkbutton(self.toolbar, text="Snap to Grid", bg="#ffffff",
                                  variable=self._snap_var,
                                  command=self._on_snap_toggle)
        snap_cb.pack(anchor="w", pady=2)

        tk.Label(self.toolbar, text="Actions:", bg="#ffffff", anchor="w").pack(fill="x", pady=(12, 2))
        tk.Button(self.toolbar, text="Auto Layout", command=self.auto_layout).pack(fill="x", pady=2)
        tk.Button(self.toolbar, text="Validate", command=self.validate_diagram).pack(fill="x", pady=2)

        self.toolbar.pack(side=tk.LEFT, fill=tk.Y)

    def _on_snap_toggle(self):
        self._snap_to_grid = self._snap_var.get()

    def _build_main_area(self):
        self.main_wrap = tk.Frame(self, bg=self.BG)
        self.main_wrap.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)

        # Status bar at the bottom
        self.status_bar = tk.Label(self.main_wrap, text="Ready", anchor="w",
                                   bg="#e5e7eb", fg="#374151", padx=8, pady=2)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Canvas area frame (left portion of main_wrap)
        self.canvas_area = tk.Frame(self.main_wrap, bg=self.BG)
        self.canvas_area.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        self.v_scroll = tk.Scrollbar(self.canvas_area, orient=tk.VERTICAL)
        self.h_scroll = tk.Scrollbar(self.canvas_area, orient=tk.HORIZONTAL)
        self.canvas = tk.Canvas(self.canvas_area, bg="#ffffff", highlightthickness=0,
                                xscrollcommand=self.h_scroll.set,
                                yscrollcommand=self.v_scroll.set)
        self.canvas.pack(side=tk.TOP, expand=True, fill=tk.BOTH)
        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.json_frame = tk.Frame(self.main_wrap, bg="#fdfdfd")
        self.json_text = tk.Text(self.json_frame, font=("Consolas", 11), undo=True, wrap="none")
        self.json_text.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        yscroll = tk.Scrollbar(self.json_frame, command=self.json_text.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.json_text.configure(yscrollcommand=yscroll.set)

        self.canvas.bind("<Configure>", self._draw_grid)
        self._update_scrollregion(initial=True)

    def _build_properties_panel(self):
        """Build the right-side properties panel (220px wide)."""
        self.prop_panel = tk.Frame(self.main_wrap, bg="#1e293b", width=220)
        self.prop_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.prop_panel.pack_propagate(False)

        tk.Label(self.prop_panel, text="Properties", bg="#1e293b", fg="#f8fafc",
                 font=("Arial", 12, "bold"), pady=8).pack(fill="x")

        # Inner scrollable content area
        self.prop_content = tk.Frame(self.prop_panel, bg="#1e293b")
        self.prop_content.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        self._show_prop_placeholder()

    def _show_prop_placeholder(self):
        for w in self.prop_content.winfo_children():
            w.destroy()
        tk.Label(self.prop_content, text="Select an item\nto view properties",
                 bg="#1e293b", fg="#64748b", font=("Arial", 10),
                 justify="center").pack(pady=40)

    def _update_properties_panel(self, obj_id, kind):
        """Populate the properties panel for the selected object."""
        for w in self.prop_content.winfo_children():
            w.destroy()

        if kind in ("node", "pool", "lane"):
            node = self.model.nodes.get(obj_id)
            if not node:
                self._show_prop_placeholder()
                return

            # Name field
            tk.Label(self.prop_content, text="Name", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(8, 1))
            self._prop_updating = True
            self._prop_name_var.set(node.text or "")
            self._prop_updating = False
            name_entry = tk.Entry(self.prop_content, textvariable=self._prop_name_var,
                                  bg="#334155", fg="#f8fafc", insertbackground="#f8fafc",
                                  relief="flat", font=("Arial", 10))
            name_entry.pack(fill="x", pady=(0, 6))

            def on_name_change(*args):
                if self._prop_updating:
                    return
                n = self.model.nodes.get(obj_id)
                if n:
                    n.text = self._prop_name_var.get()
                    self.redraw_all()

            self._prop_name_var.trace_add("write", on_name_change)

            # Type label
            tk.Label(self.prop_content, text="Type", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(4, 1))
            tk.Label(self.prop_content, text=node.type, bg="#1e293b", fg="#e2e8f0",
                     font=("Arial", 10), anchor="w").pack(fill="x", pady=(0, 6))

            # ID label
            tk.Label(self.prop_content, text="ID", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(4, 1))
            tk.Label(self.prop_content, text=node.id, bg="#1e293b", fg="#64748b",
                     font=("Arial", 8), anchor="w", wraplength=200).pack(fill="x", pady=(0, 10))

            # Colours section
            tk.Label(self.prop_content, text="Colours", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9, "bold"), anchor="w").pack(fill="x", pady=(4, 4))

            def make_colour_row(label_text, attr, current_colour):
                row = tk.Frame(self.prop_content, bg="#1e293b")
                row.pack(fill="x", pady=2)
                tk.Label(row, text=label_text, bg="#1e293b", fg="#e2e8f0",
                         font=("Arial", 9), width=8, anchor="w").pack(side=tk.LEFT)
                swatch_colour = current_colour or "#ffffff"
                swatch = tk.Frame(row, bg=swatch_colour, width=20, height=16,
                                  relief="solid", bd=1)
                swatch.pack(side=tk.LEFT, padx=4)
                swatch.pack_propagate(False)

                def pick(a=attr, s=swatch, nid=obj_id):
                    n2 = self.model.nodes.get(nid)
                    if not n2:
                        return
                    cur = getattr(n2, a) or "#ffffff"
                    result = colorchooser.askcolor(color=cur, parent=self,
                                                   title=f"Choose {a} colour")
                    if result and result[1]:
                        setattr(n2, a, result[1])
                        s.config(bg=result[1])
                        self.redraw_all()
                        self._update_properties_panel(nid, "node")

                tk.Button(row, text="Pick…", command=pick,
                          bg="#334155", fg="#f8fafc", relief="flat",
                          font=("Arial", 8), padx=4).pack(side=tk.LEFT)

            make_colour_row("Fill", "fill", node.fill)
            make_colour_row("Outline", "outline", node.outline)
            make_colour_row("Text", "text_color", node.text_color)

        elif kind == "edge":
            edge = next((e for e in self.model.edges if e.id == obj_id), None)
            if not edge:
                self._show_prop_placeholder()
                return

            # Name field
            tk.Label(self.prop_content, text="Name / Label", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(8, 1))
            self._prop_updating = True
            self._prop_name_var.set(edge.name or "")
            self._prop_updating = False
            name_entry = tk.Entry(self.prop_content, textvariable=self._prop_name_var,
                                  bg="#334155", fg="#f8fafc", insertbackground="#f8fafc",
                                  relief="flat", font=("Arial", 10))
            name_entry.pack(fill="x", pady=(0, 6))

            def on_edge_name_change(*args):
                if self._prop_updating:
                    return
                e2 = next((ex for ex in self.model.edges if ex.id == obj_id), None)
                if e2:
                    e2.name = self._prop_name_var.get()
                    self.redraw_all()

            self._prop_name_var.trace_add("write", on_edge_name_change)

            # Condition field
            tk.Label(self.prop_content, text="Condition", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(4, 1))
            self._prop_updating = True
            self._prop_cond_var.set(edge.condition or "")
            self._prop_updating = False
            cond_entry = tk.Entry(self.prop_content, textvariable=self._prop_cond_var,
                                  bg="#334155", fg="#f8fafc", insertbackground="#f8fafc",
                                  relief="flat", font=("Arial", 10))
            cond_entry.pack(fill="x", pady=(0, 6))

            def on_cond_change(*args):
                if self._prop_updating:
                    return
                e2 = next((ex for ex in self.model.edges if ex.id == obj_id), None)
                if e2:
                    val = self._prop_cond_var.get()
                    e2.condition = val if val.strip() else None
                    self.redraw_all()

            self._prop_cond_var.trace_add("write", on_cond_change)

            # Type label
            tk.Label(self.prop_content, text="Type", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(4, 1))
            tk.Label(self.prop_content, text=edge.type, bg="#1e293b", fg="#e2e8f0",
                     font=("Arial", 10), anchor="w").pack(fill="x", pady=(0, 6))

            # ID label
            tk.Label(self.prop_content, text="ID", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(4, 1))
            tk.Label(self.prop_content, text=edge.id, bg="#1e293b", fg="#64748b",
                     font=("Arial", 8), anchor="w", wraplength=200).pack(fill="x")
        else:
            self._show_prop_placeholder()

    # -------- Helpers
    def _cx(self, x):
        return self.canvas.canvasx(x)

    def _cy(self, y):
        return self.canvas.canvasy(y)

    def _event_xy_canvas(self, event):
        return self._cx(event.x), self._cy(event.y)

    def _draw_grid(self, event=None):
        """Debounced wrapper — schedules the actual grid draw to avoid thrashing on resize."""
        if self._grid_after_id is not None:
            self.after_cancel(self._grid_after_id)
        self._grid_after_id = self.after(50, self._draw_grid_now)

    def _draw_grid_now(self):
        """Draw the background grid. Call directly when an immediate redraw is needed."""
        self._grid_after_id = None
        self.canvas.delete("grid")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        step = max(2, int(self.GRID * self._zoom))
        for x in range(-5000, w + 5000, step):
            self.canvas.create_line(x, -5000, x, h + 5000, fill="#f0f0f0", tags="grid")
        for y in range(-5000, h + 5000, step):
            self.canvas.create_line(-5000, y, w + 5000, y, fill="#f0f0f0", tags="grid")
        self.canvas.tag_lower("grid")
        self._update_scrollregion()

    def _update_scrollregion(self, initial=False):
        bbox = self.canvas.bbox("all")
        pad = 2000
        if bbox:
            x1, y1, x2, y2 = bbox
            self.canvas.config(scrollregion=(x1 - pad, y1 - pad, x2 + pad, y2 + pad))
        elif initial:
            self.canvas.config(scrollregion=(-3000, -3000, 3000, 3000))

    def snap(self, x, y):
        if self._snap_to_grid:
            return round(x / self.GRID) * self.GRID, round(y / self.GRID) * self.GRID
        return x, y

    def pick_top_item(self, x, y):
        items = self.canvas.find_overlapping(x, y, x, y)
        if not items:
            return None
        for item in reversed(items):
            tags = self.canvas.gettags(item)
            if "grid" in tags or "sel_indicator" in tags:
                continue
            return item
        return None

    def pick_lane_under(self, x, y):
        items = self.canvas.find_overlapping(x, y, x, y)
        if not items:
            return None
        for item in reversed(items):
            tags = self.canvas.gettags(item)
            if any(t.startswith('lane:') for t in tags) or ('lane' in tags and 'node' not in tags):
                return item
        return None

    def _stack_layers(self):
        try:
            for tag in ('grid', 'pool', 'lane', 'edge', 'node', 'lane_handle', 'sel_indicator'):
                self.canvas.tag_lower(tag)
            self.canvas.tag_raise('grid')
            self.canvas.tag_raise('pool')
            self.canvas.tag_raise('lane')
            self.canvas.tag_raise('edge')
            self.canvas.tag_raise('node')
            self.canvas.tag_raise('lane_handle')
            self.canvas.tag_raise('sel_indicator')
        except Exception:
            pass

    def center_of_node(self, node):
        return node.x + node.w / 2, node.y + node.h / 2

    def _nodes_in_lane(self, lane):
        """Return all non-lane/pool nodes whose bounding box is inside the given lane."""
        result = []
        for n in self.model.nodes.values():
            if n.type in ("lane", "pool"):
                continue
            if (lane.x <= n.x and lane.y <= n.y and
                    (n.x + n.w) <= (lane.x + lane.w) and
                    (n.y + n.h) <= (lane.y + lane.h)):
                result.append(n)
        return result

    def redraw_all(self):
        self.canvas.delete("all")
        self._node_by_item.clear()
        self._edge_by_item.clear()
        self._label_by_item.clear()
        self._lane_handle_to_info.clear()
        self._draw_grid_now()
        for n in self.model.nodes.values():
            if n.type == "pool":
                self.draw_pool(n)
        for n in self.model.nodes.values():
            if n.type == "lane":
                self.draw_lane(n)
        for e in self.model.edges:
            self.draw_edge(e)
        for n in self.model.nodes.values():
            if n.type not in ("lane", "pool"):
                self.draw_node(n)
        if self._active_lane_id and self._active_lane_id in self.model.nodes:
            self._draw_lane_handles(self.model.nodes[self._active_lane_id])
        self._update_scrollregion()
        self._stack_layers()
        self._draw_selection_overlays()

    # -------- Drawing
    def draw_pool(self, pool_node):
        x = self._mc(pool_node.x)
        y = self._mc(pool_node.y)
        w = self._mc(pool_node.w)
        h = self._mc(pool_node.h)
        font_size = max(6, int(12 * self._zoom))
        rect = self.canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=pool_node.fill, outline=pool_node.outline, width=2,
            tags=("pool", f"pool:{pool_node.id}"),
        )
        label = self.canvas.create_text(
            x + self._mc(8), y + self._mc(16), text=pool_node.text, anchor='w',
            font=('Arial', font_size, 'bold'), fill=pool_node.text_color,
            tags=("pool", f"pool:{pool_node.id}"),
        )
        self._node_by_item[rect] = pool_node.id
        self._label_by_item[label] = (pool_node.id, 'pool_label')

    def draw_lane(self, lane_node):
        x = self._mc(lane_node.x)
        y = self._mc(lane_node.y)
        w = self._mc(lane_node.w)
        h = self._mc(lane_node.h)
        font_size = max(6, int(12 * self._zoom))
        rect = self.canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=lane_node.fill, outline=lane_node.outline, width=2,
            tags=("lane", f"lane:{lane_node.id}"),
        )
        label = self.canvas.create_text(
            x + w - self._mc(8), y + self._mc(16), text=lane_node.text, anchor='e',
            font=('Arial', font_size, 'bold'), fill=lane_node.text_color,
            tags=("lane", f"lane:{lane_node.id}"),
        )
        self._node_by_item[rect] = lane_node.id
        self._label_by_item[label] = (lane_node.id, 'lane_label')

    def draw_node(self, node):
        x = self._mc(node.x)
        y = self._mc(node.y)
        w = self._mc(node.w)
        h = self._mc(node.h)
        font_large = max(6, int(11 * self._zoom))
        font_small = max(6, int(10 * self._zoom))
        font_marker = max(6, int(12 * self._zoom))
        tag = (f"node:{node.id}", "node")

        if node.type in ("startEvent", "endEvent"):
            r = min(w, h) / 2
            cx, cy = x + w / 2, y + h / 2
            ow = 4 if node.type == "endEvent" else 2
            oval = self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=node.fill, outline=node.outline, width=ow, tags=tag,
            )
            label = self.canvas.create_text(
                cx, cy, text=node.text, font=("Arial", font_large), fill=node.text_color, tags=tag,
            )
            self._node_by_item[oval] = node.id
            self._label_by_item[label] = (node.id, 'node_label')

        elif node.type == "intermediateEvent":
            # Double-ring circle
            r = min(w, h) / 2
            cx, cy = x + w / 2, y + h / 2
            outer = self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=node.fill, outline=node.outline, width=2, tags=tag,
            )
            inner_r = r * 0.75
            self.canvas.create_oval(
                cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
                fill="", outline=node.outline, width=1, tags=tag,
            )
            label = self.canvas.create_text(
                cx, cy + r + self._mc(12), text=node.text,
                font=("Arial", font_small), fill=node.text_color, tags=tag,
            )
            self._node_by_item[outer] = node.id
            self._label_by_item[label] = (node.id, 'node_label')

        elif node.type in ("exclusiveGateway", "parallelGateway", "inclusiveGateway"):
            points = [x + w / 2, y, x + w, y + h / 2, x + w / 2, y + h, x, y + h / 2]
            poly = self.canvas.create_polygon(
                points, fill=node.fill, outline=node.outline, width=2, tags=tag,
            )
            if node.type == "exclusiveGateway":
                marker_text = "X"
            elif node.type == "parallelGateway":
                marker_text = "+"
            else:
                marker_text = "O"
            marker = self.canvas.create_text(
                x + w / 2, y + h / 2, text=marker_text,
                font=("Arial", font_marker, 'bold'), fill=node.text_color, tags=tag,
            )
            text_label = self.canvas.create_text(
                x + w / 2, y + h + self._mc(14), text=node.text,
                font=("Arial", font_small), fill=node.text_color, tags=tag,
            )
            self._node_by_item[poly] = node.id
            self._label_by_item[marker] = (node.id, 'gateway_marker')
            self._label_by_item[text_label] = (node.id, 'node_label')

        else:
            rect = self.canvas.create_rectangle(
                x, y, x + w, y + h,
                fill=node.fill, outline=node.outline, width=2, tags=tag,
            )
            label = self.canvas.create_text(
                x + w / 2, y + h / 2, text=node.text,
                font=("Arial", font_large), fill=node.text_color, tags=tag,
            )
            self._node_by_item[rect] = node.id
            self._label_by_item[label] = (node.id, 'node_label')

    # -------- Orthogonal edge routing
    def _connection_point(self, from_node, to_node):
        """Return the best border point on from_node facing toward to_node (model coords)."""
        fx = from_node.x + from_node.w / 2
        fy = from_node.y + from_node.h / 2
        tx = to_node.x + to_node.w / 2
        ty = to_node.y + to_node.h / 2
        dx = tx - fx
        dy = ty - fy
        if abs(dx) >= abs(dy):
            # Mostly horizontal
            if dx >= 0:
                return from_node.x + from_node.w, fy
            else:
                return from_node.x, fy
        else:
            # Mostly vertical
            if dy >= 0:
                return fx, from_node.y + from_node.h
            else:
                return fx, from_node.y

    def _edge_waypoints(self, src_node, tgt_node):
        """Return flat list of model-coord waypoints for orthogonal routing."""
        p1x, p1y = self._connection_point(src_node, tgt_node)
        p2x, p2y = self._connection_point(tgt_node, src_node)
        dx = abs(p2x - p1x)
        dy = abs(p2y - p1y)
        if dx >= dy:
            # Horizontal bend
            mx = (p1x + p2x) / 2
            return [p1x, p1y, mx, p1y, mx, p2y, p2x, p2y]
        else:
            # Vertical bend
            my = (p1y + p2y) / 2
            return [p1x, p1y, p1x, my, p2x, my, p2x, p2y]

    def draw_edge(self, edge):
        if edge.src not in self.model.nodes or edge.tgt not in self.model.nodes:
            return
        s = self.model.nodes[edge.src]
        t = self.model.nodes[edge.tgt]

        # Get waypoints in model coords, scale to canvas coords
        model_pts = self._edge_waypoints(s, t)
        canvas_pts = [self._mc(v) for v in model_pts]

        font_size = max(6, int(10 * self._zoom))

        if edge.type == "sequenceFlow":
            line = self.canvas.create_line(
                *canvas_pts, arrow='last', width=2, fill='#111827',
                smooth=False, tags=("edge",),
            )
        elif edge.type == "messageFlow":
            line = self.canvas.create_line(
                *canvas_pts, arrow='last', width=2, dash=(6, 4), fill='#1f2937',
                smooth=False, tags=("edge",),
            )
        else:
            line = self.canvas.create_line(
                *canvas_pts, width=2, dash=(2, 3), fill='#6b7280',
                smooth=False, tags=("edge",),
            )
        self._edge_by_item[line] = edge.id

        # Label at midpoint of waypoint list
        mid_idx = len(canvas_pts) // 2
        if len(canvas_pts) >= 4:
            mx = (canvas_pts[mid_idx - 2] + canvas_pts[mid_idx]) / 2
            my = (canvas_pts[mid_idx - 1] + canvas_pts[mid_idx + 1]) / 2
        else:
            mx = (canvas_pts[0] + canvas_pts[-2]) / 2
            my = (canvas_pts[1] + canvas_pts[-1]) / 2

        label = self.canvas.create_text(
            mx, my - self._mc(10), text=edge.name or "",
            font=("Arial", font_size, 'italic'), fill="#374151", tags=("edge",),
        )
        self._label_by_item[label] = (edge.id, 'edge_label')

        # Condition label
        if edge.condition:
            cond_label = self.canvas.create_text(
                mx + self._mc(4), my + self._mc(6), text=f"[{edge.condition}]",
                font=("Arial", max(6, int(8 * self._zoom)), 'italic'),
                fill="#6b7280", tags=("edge",),
            )
            self._label_by_item[cond_label] = (edge.id, 'edge_condition')

    # -------- Lane handles (resize)
    def _clear_lane_handles(self):
        for item in list(self._lane_handle_to_info.keys()):
            self.canvas.delete(item)
        self._lane_handle_to_info.clear()

    def _draw_lane_handles(self, lane_node):
        self._clear_lane_handles()
        x = self._mc(lane_node.x)
        y = self._mc(lane_node.y)
        w = self._mc(lane_node.w)
        h = self._mc(lane_node.h)
        cx, cy = x + w / 2, y + h / 2
        pts = {
            "nw": (x, y), "n": (cx, y), "ne": (x + w, y),
            "e": (x + w, cy), "se": (x + w, y + h),
            "s": (cx, y + h), "sw": (x, y + h), "w": (x, cy),
        }
        size = max(4, int(8 * self._zoom))
        for anchor, (hx, hy) in pts.items():
            r = self.canvas.create_rectangle(
                hx - size / 2, hy - size / 2, hx + size / 2, hy + size / 2,
                fill="#2563eb", outline="#1e3a8a", tags=("lane_handle",),
            )
            self._lane_handle_to_info[r] = (lane_node.id, anchor)
        self._stack_layers()

    def _update_lane_graphics(self, lane_node):
        x = self._mc(lane_node.x)
        y = self._mc(lane_node.y)
        w = self._mc(lane_node.w)
        h = self._mc(lane_node.h)
        items = self.canvas.find_withtag(f"lane:{lane_node.id}")
        for it in items:
            t = self.canvas.type(it)
            if t == 'rectangle':
                self.canvas.coords(it, x, y, x + w, y + h)
            elif t == 'text':
                self.canvas.coords(it, x + w - self._mc(8), y + self._mc(16))
        if self._active_lane_id == lane_node.id:
            self._draw_lane_handles(lane_node)

    # -------- Selection overlays
    def _draw_selection_overlays(self):
        """Draw dashed blue selection rectangles for all selected nodes."""
        self.canvas.delete("sel_indicator")
        pad = 4

        def draw_overlay_for_nid(nid):
            n = self.model.nodes.get(nid)
            if not n:
                return
            x = self._mc(n.x) - pad
            y = self._mc(n.y) - pad
            x2 = self._mc(n.x + n.w) + pad
            y2 = self._mc(n.y + n.h) + pad
            self.canvas.create_rectangle(
                x, y, x2, y2,
                outline="#2563eb", width=2, dash=(4, 3), fill="",
                tags=("sel_indicator",),
            )

        if self._multi_select:
            for nid in self._multi_select:
                draw_overlay_for_nid(nid)
        elif self._selected_item and self._selected_type in ("node", "pool", "lane"):
            nid = self.item_to_node_id(self._selected_item)
            if not nid and self._selected_item in self._label_by_item:
                nid, _ = self._label_by_item[self._selected_item]
            if nid:
                draw_overlay_for_nid(nid)

        try:
            self.canvas.tag_raise("sel_indicator")
        except Exception:
            pass

    # -------- Selection & Interaction
    def get_item_kind(self, item_id):
        if item_id in self._lane_handle_to_info:
            return "lane_handle"
        if item_id in self._node_by_item:
            nid = self._node_by_item[item_id]
            n = self.model.nodes.get(nid)
            if n:
                if n.type == "lane":
                    return "lane"
                if n.type == "pool":
                    return "pool"
            return "node"
        if item_id in self._edge_by_item:
            return "edge"
        if item_id in self._label_by_item:
            obj_id, _ = self._label_by_item[item_id]
            if obj_id in self.model.nodes:
                t = self.model.nodes[obj_id].type
                if t == "lane":
                    return "lane"
                if t == "pool":
                    return "pool"
                return "node"
            return "edge"
        return None

    def item_to_node_id(self, item_id):
        return self._node_by_item.get(item_id)

    def item_to_edge_id(self, item_id):
        return self._edge_by_item.get(item_id)

    def _resolve_node_id_from_item(self, item):
        nid = self.item_to_node_id(item)
        if not nid and item in self._label_by_item:
            nid, _ = self._label_by_item[item]
        return nid

    def _resolve_edge_id_from_item(self, item):
        eid = self.item_to_edge_id(item)
        if not eid and item in self._label_by_item:
            eid, _ = self._label_by_item[item]
        return eid

    # -------- Bindings
    def _bind_canvas_events(self):
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.bind("<Delete>", self.on_delete)
        # Panning with middle button only
        self.canvas.bind("<ButtonPress-2>", self._pan_scan_mark)
        self.canvas.bind("<B2-Motion>", self._pan_scan_dragto)

    def _bind_pan_keys(self):
        self.bind_all("<KeyPress-space>", self._on_space_down)
        self.bind_all("<KeyRelease-space>", self._on_space_up)

    def _bind_mouse_wheel(self):
        self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind_all("<Button-4>", self._on_mouse_wheel_linux_up)
        self.canvas.bind_all("<Button-5>", self._on_mouse_wheel_linux_down)

    def _bind_keyboard_shortcuts(self):
        """Bind single-key shortcuts for tools (only when BPMN view is active)."""
        key_to_tool = {
            's': 'select',
            't': 'task',
            'b': 'startEvent',
            'e': 'endEvent',
            'x': 'exclusiveGateway',
            'p': 'parallelGateway',
            'i': 'inclusiveGateway',
            'm': 'intermediateEvent',
            'l': 'lane',
            'o': 'pool',
            'c': 'connector',
            'f': 'msgConnector',
        }
        for key, tool in key_to_tool.items():
            def make_handler(t):
                def handler(event):
                    if self.view_mode != "bpmn":
                        return
                    if isinstance(self.focus_get(), (tk.Entry, tk.Text)):
                        return
                    self._current_tool.set(t)
                return handler
            self.bind_all(key, make_handler(tool))

    # -------- Panning
    def _on_space_down(self, event):
        self.canvas.config(cursor="fleur")

    def _on_space_up(self, event):
        self.canvas.config(cursor="")

    def _pan_scan_mark(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _pan_scan_dragto(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_mouse_wheel(self, event):
        # Ctrl+scroll = zoom
        if event.state & 0x0004:
            if event.delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        elif event.state & 0x0001:
            # Shift+scroll = horizontal
            self.canvas.xview_scroll(-1 * int(event.delta / 120), "units")
        else:
            self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def _on_mouse_wheel_linux_up(self, event):
        if event.state & 0x0004:
            self.zoom_in()
        elif event.state & 0x0001:
            self.canvas.xview_scroll(-1, "units")
        else:
            self.canvas.yview_scroll(-1, "units")

    def _on_mouse_wheel_linux_down(self, event):
        if event.state & 0x0004:
            self.zoom_out()
        elif event.state & 0x0001:
            self.canvas.xview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(1, "units")

    # -------- Events
    def on_left_click(self, event):
        if self.view_mode != "bpmn":
            return
        cx, cy = self._event_xy_canvas(event)
        # Convert canvas coords to model coords
        mx, my = self._cm(cx), self._cm(cy)
        sx, sy = self.snap(mx, my)
        tool = self._current_tool.get()
        item = self.pick_top_item(cx, cy)
        clicked_kind = self.get_item_kind(item) if item else None

        # Ctrl+click on node = toggle multi-select
        if event.state & 0x0004 and tool == "select":
            if clicked_kind in ("node", "pool"):
                nid = self._resolve_node_id_from_item(item)
                if nid:
                    if nid in self._multi_select:
                        self._multi_select.discard(nid)
                    else:
                        self._multi_select.add(nid)
                    self._draw_selection_overlays()
                return

        # Lane handle resize begin
        if clicked_kind == "lane_handle":
            lane_id, anchor = self._lane_handle_to_info.get(item, (None, None))
            if lane_id and lane_id in self.model.nodes:
                ln = self.model.nodes[lane_id]
                self._resizing_lane = {
                    "lane_id": lane_id,
                    "anchor": anchor,
                    "start_mouse": (cx, cy),
                    "start_geom": (ln.x, ln.y, ln.w, ln.h),
                }
            return

        # Prefer choosing lane under edges for selection
        if tool == "select" and clicked_kind in (None, 'edge'):
            lane_item = self.pick_lane_under(cx, cy)
            if lane_item is not None:
                item = lane_item
                clicked_kind = 'lane'

        if tool == "select":
            if clicked_kind is None:
                # Start rubber-band on empty canvas
                self._multi_select.clear()
                self._rubber_band_start = (cx, cy)
                self._rubber_band_item = None
                self._draw_selection_overlays()
                return

            if clicked_kind == "lane":
                lane_item = item
                tags = self.canvas.gettags(lane_item) if lane_item else ()
                lane_tag = None
                for t in tags:
                    if t.startswith('lane:'):
                        lane_tag = t
                        break
                if lane_tag:
                    for cand in self.canvas.find_withtag(lane_tag):
                        if self.canvas.type(cand) == 'rectangle':
                            lane_item = cand
                            break
                nid = self.item_to_node_id(lane_item) or self._label_by_item.get(lane_item, (None, None))[0]
                if nid and nid in self.model.nodes:
                    self._active_lane_id = nid
                    ln = self.model.nodes[nid]
                    self._dragging_lane = {'lane_id': nid, 'offset': (mx - ln.x, my - ln.y)}
                    self._selected_item = lane_item
                    self._selected_type = 'lane'
                    self._draw_lane_handles(ln)
                    self._stack_layers()
                    self._multi_select.clear()
                    self._draw_selection_overlays()
                    self._update_properties_panel(nid, "lane")
                return

            # Node / pool / edge
            self._active_lane_id = None
            self._clear_lane_handles()
            self._selected_item = item
            self._selected_type = clicked_kind

            if clicked_kind in ("node", "pool"):
                nid = self._resolve_node_id_from_item(item)
                if nid and nid in self.model.nodes:
                    n = self.model.nodes[nid]
                    # If node is in multi-select, start multi-drag
                    if nid in self._multi_select:
                        self._primary_drag_nid = nid
                        self._drag_offset = (mx - n.x, my - n.y)
                    else:
                        # Single select
                        self._multi_select.clear()
                        self._drag_offset = (mx - n.x, my - n.y)
                        self._update_properties_panel(nid, "node")
                else:
                    self._multi_select.clear()
                    self._drag_offset = (0, 0)
                self._draw_selection_overlays()

            elif clicked_kind == "edge":
                self._multi_select.clear()
                eid = self._resolve_edge_id_from_item(item)
                if eid:
                    self._update_properties_panel(eid, "edge")
                self._draw_selection_overlays()
            return

        # Tool: add node
        node_tools = ("startEvent", "endEvent", "task", "exclusiveGateway",
                      "parallelGateway", "inclusiveGateway", "intermediateEvent",
                      "lane", "pool")
        if tool in node_tools:
            self._multi_select.clear()
            if tool in ("startEvent", "endEvent", "intermediateEvent"):
                offset_y = 30
            elif tool in ("exclusiveGateway", "parallelGateway", "inclusiveGateway"):
                offset_y = 40
            elif tool == "lane":
                offset_y = 75
            elif tool == "pool":
                offset_y = 110
            else:
                offset_y = 40
            node = self.model.add_node(tool, sx - 60, sy - offset_y)
            if tool == "lane":
                node.x, node.y = 40, max(20, sy - 75)
            elif tool == "pool":
                node.x, node.y = 20, max(10, sy - 110)
            if node.type == "lane":
                self.draw_lane(node)
            elif node.type == "pool":
                self.draw_pool(node)
            else:
                self.draw_node(node)
            self._update_scrollregion()
            self._stack_layers()
            self._push_history(f"add {tool}")
            return

        if tool in ("connector", "msgConnector"):
            self._multi_select.clear()
            if clicked_kind in ("node", "pool"):
                nid = self._resolve_node_id_from_item(item)
                if not self._connect_source:
                    self._connect_source = nid
                    self._flash_message(f"Connector: source={nid}. Click target node.")
                else:
                    if nid == self._connect_source:
                        self._flash_message("Connector canceled (same node).")
                        self._connect_source = None
                        return
                    etype = "messageFlow" if tool == "msgConnector" else "sequenceFlow"
                    e = self.model.add_edge(self._connect_source, nid, etype=etype)
                    self._connect_source = None
                    self.draw_edge(e)
                    self._update_scrollregion()
                    self._stack_layers()
                    self._push_history(f"add {etype}")
            else:
                self._flash_message("Connector: click a node to choose source/target.")
            return

    def on_drag(self, event):
        if self.view_mode != "bpmn":
            return
        cx, cy = self._event_xy_canvas(event)
        mx, my = self._cm(cx), self._cm(cy)

        # Rubber-band selection
        if self._rubber_band_start is not None:
            rbx, rby = self._rubber_band_start
            if self._rubber_band_item:
                self.canvas.delete(self._rubber_band_item)
            self._rubber_band_item = self.canvas.create_rectangle(
                rbx, rby, cx, cy,
                outline="#2563eb", width=1, dash=(4, 3), fill="",
                tags=("sel_indicator",),
            )
            return

        # Lane resizing
        if self._resizing_lane:
            lane_id = self._resizing_lane["lane_id"]
            if lane_id not in self.model.nodes:
                return
            anchor = self._resizing_lane["anchor"]
            scx, scy = self._resizing_lane["start_mouse"]
            lx, ly, lw, lh = self._resizing_lane["start_geom"]
            # Convert canvas delta to model delta
            dcx, dcy = cx - scx, cy - scy
            dx, dy = self._cm(dcx), self._cm(dcy)
            nx, ny, nw, nh = lx, ly, lw, lh
            minw, minh = 200, 80
            if anchor in ("nw", "w", "sw"):
                nx = lx + dx
                nw = lw - dx
            if anchor in ("ne", "e", "se"):
                nw = lw + dx
            if anchor in ("nw", "n", "ne"):
                ny = ly + dy
                nh = lh - dy
            if anchor in ("sw", "s", "se"):
                nh = lh + dy
            if nw < minw:
                if anchor in ("nw", "w", "sw"):
                    nx = lx + (lw - minw)
                nw = minw
            if nh < minh:
                if anchor in ("nw", "n", "ne"):
                    ny = ly + (lh - minh)
                nh = minh
            lane = self.model.nodes[lane_id]
            lane.x, lane.y, lane.w, lane.h = nx, ny, nw, nh
            self._update_lane_graphics(lane)
            self._changed_during_drag = True
            return

        # Lane dragging — move the lane and all nodes inside it
        if self._dragging_lane:
            lane_id = self._dragging_lane.get('lane_id')
            if lane_id and lane_id in self.model.nodes:
                ln = self.model.nodes[lane_id]
                offx, offy = self._dragging_lane.get('offset', (0, 0))
                nx, ny = self.snap(mx - offx, my - offy)
                dx, dy = nx - ln.x, ny - ln.y
                if dx or dy:
                    children = self._nodes_in_lane(ln)
                    ln.x, ln.y = nx, ny
                    self.canvas.move(f"lane:{lane_id}",
                                     dx * self._zoom, dy * self._zoom)
                    for n in children:
                        n.x += dx
                        n.y += dy
                        self.canvas.move(f"node:{n.id}",
                                         dx * self._zoom, dy * self._zoom)
                    self.canvas.delete("edge")
                    self._edge_by_item.clear()
                    for e in self.model.edges:
                        self.draw_edge(e)
                    if self._active_lane_id == lane_id:
                        self._draw_lane_handles(ln)
                    self._stack_layers()
                    self._changed_during_drag = True
            return

        # Multi-node drag
        if self._multi_select and self._primary_drag_nid:
            pnid = self._primary_drag_nid
            if pnid not in self.model.nodes:
                return
            pn = self.model.nodes[pnid]
            nx, ny = self.snap(mx - self._drag_offset[0], my - self._drag_offset[1])
            dx, dy = nx - pn.x, ny - pn.y
            if not (dx or dy):
                return
            for nid in self._multi_select:
                if nid not in self.model.nodes:
                    continue
                n = self.model.nodes[nid]
                n.x += dx
                n.y += dy
                self.canvas.move(f"node:{nid}",
                                 dx * self._zoom, dy * self._zoom)
            self.canvas.delete("edge")
            self._edge_by_item.clear()
            for e in self.model.edges:
                self.draw_edge(e)
            if self._active_lane_id and self._active_lane_id in self.model.nodes:
                self._draw_lane_handles(self.model.nodes[self._active_lane_id])
            self._update_scrollregion()
            self._stack_layers()
            self._draw_selection_overlays()
            self._changed_during_drag = True
            return

        # Single node dragging
        if not self._selected_item or self._selected_type != "node":
            return
        nid = self._resolve_node_id_from_item(self._selected_item)
        if not nid or nid not in self.model.nodes:
            return
        n = self.model.nodes[nid]
        nx, ny = self.snap(mx - self._drag_offset[0], my - self._drag_offset[1])
        dx, dy = nx - n.x, ny - n.y
        if not (dx or dy):
            return
        n.x, n.y = nx, ny
        self.canvas.move(f"node:{nid}", dx * self._zoom, dy * self._zoom)
        # Redraw edges
        self.canvas.delete("edge")
        self._edge_by_item.clear()
        for e in self.model.edges:
            self.draw_edge(e)
        if self._active_lane_id and self._active_lane_id in self.model.nodes:
            self._draw_lane_handles(self.model.nodes[self._active_lane_id])
        self._update_scrollregion()
        self._stack_layers()
        self._draw_selection_overlays()
        self._changed_during_drag = True

    def on_release(self, event):
        # Finish rubber-band selection
        if self._rubber_band_start is not None:
            cx, cy = self._event_xy_canvas(event)
            rbx, rby = self._rubber_band_start
            # Convert to model coords
            x1m = self._cm(min(rbx, cx))
            y1m = self._cm(min(rby, cy))
            x2m = self._cm(max(rbx, cx))
            y2m = self._cm(max(rby, cy))
            # Find nodes whose bbox intersects the rubber-band
            for nid, n in self.model.nodes.items():
                if n.type in ("lane", "pool"):
                    continue
                nx1, ny1, nx2, ny2 = n.x, n.y, n.x + n.w, n.y + n.h
                if nx2 > x1m and nx1 < x2m and ny2 > y1m and ny1 < y2m:
                    self._multi_select.add(nid)
            if self._rubber_band_item:
                self.canvas.delete(self._rubber_band_item)
                self._rubber_band_item = None
            self._rubber_band_start = None
            self._draw_selection_overlays()
            return

        if self._resizing_lane:
            self._resizing_lane = None
            self._stack_layers()
            self._update_scrollregion()
            if self._changed_during_drag:
                self._push_history("resize lane")
                self._changed_during_drag = False
        elif self._dragging_lane:
            self._dragging_lane = None
            self._stack_layers()
            self._update_scrollregion()
            if self._active_lane_id and self._active_lane_id in self.model.nodes:
                self._draw_lane_handles(self.model.nodes[self._active_lane_id])
            if self._changed_during_drag:
                self._push_history("move lane")
                self._changed_during_drag = False
        elif self._changed_during_drag:
            self._push_history("move node")
            self._changed_during_drag = False

        self._primary_drag_nid = None

    def on_double_click(self, event):
        if self.view_mode != "bpmn":
            return
        cx, cy = self._event_xy_canvas(event)
        item = self.pick_top_item(cx, cy)
        if not item:
            return
        kind = self.get_item_kind(item)
        if kind in ("node", "lane", "pool"):
            nid = self._resolve_node_id_from_item(item)
            if nid and nid in self.model.nodes:
                n = self.model.nodes[nid]
                new = simpledialog.askstring(
                    "Rename", f"New name for {n.type}:", initialvalue=n.text, parent=self,
                )
                if new is not None and new.strip():
                    n.text = new.strip()
                    self.redraw_all()
                    self._push_history("rename")
        elif kind == "edge":
            eid = self._resolve_edge_id_from_item(item)
            if eid:
                e = next((x for x in self.model.edges if x.id == eid), None)
                if e is not None:
                    new = simpledialog.askstring(
                        "Label", "Edge label:", initialvalue=e.name, parent=self,
                    )
                    if new is not None:
                        e.name = new
                        self.redraw_all()
                        self._push_history("rename")

    def on_delete(self, event):
        if self.view_mode != "bpmn":
            return
        # Multi-select delete
        if self._multi_select:
            for nid in list(self._multi_select):
                if nid == self._active_lane_id:
                    self._active_lane_id = None
                    self._clear_lane_handles()
                self.model.delete_node(nid)
            self._multi_select.clear()
            self._selected_item = None
            self.redraw_all()
            self._push_history("delete")
            return

        if not self._selected_item:
            self._flash_message("Nothing selected to delete")
            return
        kind = self.get_item_kind(self._selected_item)
        if kind in ("node", "lane", "pool"):
            nid = self._resolve_node_id_from_item(self._selected_item)
            if nid:
                if nid == self._active_lane_id:
                    self._active_lane_id = None
                    self._clear_lane_handles()
                self.model.delete_node(nid)
                self._selected_item = None
                self.redraw_all()
                self._push_history("delete")
        elif kind == "edge":
            eid = self._resolve_edge_id_from_item(self._selected_item)
            if eid:
                self.model.delete_edge(eid)
                self._selected_item = None
                self.redraw_all()
                self._push_history("delete")

    # -------- Context menu (right-click)
    def on_right_click(self, event):
        if self.view_mode != "bpmn":
            return
        cx, cy = self._event_xy_canvas(event)
        item = self.pick_top_item(cx, cy)
        if not item:
            return
        kind = self.get_item_kind(item)
        if kind is None:
            return
        if kind == "lane":
            lane_item = item
            tags = self.canvas.gettags(lane_item) if lane_item else ()
            lane_tag = None
            for t in tags:
                if t.startswith('lane:'):
                    lane_tag = t
                    break
            if lane_tag:
                for cand in self.canvas.find_withtag(lane_tag):
                    if self.canvas.type(cand) == 'rectangle':
                        lane_item = cand
                        break
            self._selected_item = lane_item
            self._selected_type = 'lane'
            nid = self.item_to_node_id(lane_item) or self._label_by_item.get(lane_item, (None, None))[0]
            if nid and nid in self.model.nodes:
                self._active_lane_id = nid
                self._draw_lane_handles(self.model.nodes[nid])
                self._stack_layers()
        elif kind in ("node", "pool", "edge"):
            self._selected_item = item
            self._selected_type = kind
            self._active_lane_id = None
            self._clear_lane_handles()
        else:
            return

        # Show/hide colour menu only for non-edge items
        try:
            if kind == "edge":
                self._ctx_menu.entryconfig("Change Colour…", state="disabled")
            else:
                self._ctx_menu.entryconfig("Change Colour…", state="normal")
        except Exception:
            pass

        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def ctx_delete(self):
        if self.view_mode != "bpmn":
            return
        if not self._selected_item:
            self._flash_message("Nothing selected to delete")
            return
        self.on_delete(None)

    def ctx_bring_forward(self):
        if self.view_mode != "bpmn" or not self._selected_item:
            return
        self._raise_or_lower_selected(True)

    def ctx_send_backward(self):
        if self.view_mode != "bpmn" or not self._selected_item:
            return
        self._raise_or_lower_selected(False)

    def _raise_or_lower_selected(self, raise_it: bool):
        kind = self.get_item_kind(self._selected_item)
        if kind is None:
            return
        items_to_move = []
        if kind in ("lane", "pool", "node"):
            nid = self._resolve_node_id_from_item(self._selected_item)
            if not nid or nid not in self.model.nodes:
                return
            obj = self.model.nodes[nid]
            if obj.type == "lane":
                tag = f"lane:{nid}"
            elif obj.type == "pool":
                tag = f"pool:{nid}"
            else:
                tag = f"node:{nid}"
            items_to_move = list(self.canvas.find_withtag(tag))
        elif kind == "edge":
            eid = self._resolve_edge_id_from_item(self._selected_item)
            if not eid:
                return
            for it, mapped in list(self._edge_by_item.items()):
                if mapped == eid:
                    items_to_move.append(it)
            for it, (obj_id, lk) in list(self._label_by_item.items()):
                if lk == "edge_label" and obj_id == eid:
                    items_to_move.append(it)
        for it in items_to_move:
            try:
                self.canvas.tag_raise(it) if raise_it else self.canvas.tag_lower(it)
            except Exception:
                pass
        self._stack_layers()

    # -------- Colour picking via context menu
    def _pick_colour(self, attr):
        """Pick a colour for the selected node's attribute ('fill', 'outline', 'text_color')."""
        if not self._selected_item:
            return
        nid = self._resolve_node_id_from_item(self._selected_item)
        if not nid or nid not in self.model.nodes:
            return
        node = self.model.nodes[nid]
        cur = getattr(node, attr, None) or "#ffffff"
        label_map = {"fill": "Fill Colour", "outline": "Outline Colour", "text_color": "Text Colour"}
        result = colorchooser.askcolor(color=cur, parent=self,
                                       title=f"Choose {label_map.get(attr, attr)}")
        if result and result[1]:
            setattr(node, attr, result[1])
            self.redraw_all()
            self._push_history(f"change colour {attr}")

    # -------- Copy/Paste
    def cmd_copy(self):
        """Copy selected nodes to clipboard."""
        if self.view_mode != "bpmn":
            return
        nids_to_copy = set()
        if self._multi_select:
            nids_to_copy = set(self._multi_select)
        elif self._selected_item:
            nid = self._resolve_node_id_from_item(self._selected_item)
            if nid and nid in self.model.nodes:
                nids_to_copy.add(nid)
        if not nids_to_copy:
            self._flash_message("Nothing to copy")
            return
        self._clipboard = []
        for nid in nids_to_copy:
            n = self.model.nodes[nid]
            self._clipboard.append(copy.deepcopy(n.to_dict()))
        self._flash_message(f"Copied {len(self._clipboard)} node(s)")

    def cmd_paste(self):
        """Paste clipboard nodes with offset."""
        if self.view_mode != "bpmn":
            return
        if not self._clipboard:
            self._flash_message("Clipboard is empty")
            return
        self._multi_select.clear()
        offset = 30
        for nd in self._clipboard:
            ntype = nd.get("type", "task")
            x = (nd.get("x") or 0) + offset
            y = (nd.get("y") or 0) + offset
            w = nd.get("w", 120)
            h = nd.get("h", 60)
            text = nd.get("name", ntype)
            style = nd.get("style", {}) or {}
            new_node = self.model.add_node_with_id(
                self.model.gen_id(_TYPE_PREFIX.get(ntype, ntype)),
                ntype, x, y, w, h, text,
                fill=style.get("fill"), outline=style.get("outline"),
                text_color=style.get("text"),
            )
            self._multi_select.add(new_node.id)
        self.redraw_all()
        self._push_history("paste")
        self._flash_message(f"Pasted {len(self._clipboard)} node(s)")

    def cmd_select_all(self):
        """Select all non-lane/pool nodes."""
        if self.view_mode != "bpmn":
            return
        self._multi_select.clear()
        for nid, n in self.model.nodes.items():
            if n.type not in ("lane", "pool"):
                self._multi_select.add(nid)
        self._draw_selection_overlays()

    # -------- Auto-layout
    def auto_layout(self):
        """Layered left-to-right layout of process nodes."""
        process_nodes = {nid: n for nid, n in self.model.nodes.items()
                         if n.type not in ("lane", "pool")}
        if not process_nodes:
            self._flash_message("No process nodes to lay out.")
            return

        # Build successor/predecessor maps from sequence flows
        successors = {nid: [] for nid in process_nodes}
        predecessors = {nid: [] for nid in process_nodes}
        for e in self.model.edges:
            if e.type == "sequenceFlow" and e.src in process_nodes and e.tgt in process_nodes:
                successors[e.src].append(e.tgt)
                predecessors[e.tgt].append(e.src)

        # BFS from start nodes (no incoming flows)
        start_nodes = [nid for nid in process_nodes if not predecessors[nid]]
        if not start_nodes:
            # Cycle: pick node with fewest predecessors
            start_nodes = [min(process_nodes.keys(),
                               key=lambda nid: len(predecessors[nid]))]

        layers = {}
        visited = set()
        queue = list(start_nodes)
        for nid in queue:
            layers[nid] = 0
            visited.add(nid)

        i = 0
        while i < len(queue):
            nid = queue[i]
            i += 1
            for succ in successors[nid]:
                if succ not in visited:
                    layers[succ] = layers[nid] + 1
                    visited.add(succ)
                    queue.append(succ)
                else:
                    layers[succ] = max(layers.get(succ, 0), layers[nid] + 1)

        # Assign remaining unvisited nodes
        for nid in process_nodes:
            if nid not in layers:
                layers[nid] = 0

        # Group by layer
        layer_groups = {}
        for nid, layer in layers.items():
            layer_groups.setdefault(layer, []).append(nid)

        START_X = 80
        H_GAP = 60
        V_GAP = 40
        max_w = max((process_nodes[nid].w for nid in process_nodes), default=160)
        max_h = max((process_nodes[nid].h for nid in process_nodes), default=80)
        centre_y = 300

        for layer, nids in sorted(layer_groups.items()):
            total_h = len(nids) * max_h + (len(nids) - 1) * V_GAP
            start_y = centre_y - total_h / 2
            x = START_X + layer * (max_w + H_GAP)
            for idx, nid in enumerate(nids):
                n = process_nodes[nid]
                n.x = x
                n.y = start_y + idx * (max_h + V_GAP)

        self._push_history("auto layout")
        self.redraw_all()
        self._flash_message("Auto layout applied.")

    # -------- Diagram Validation
    def validate_diagram(self):
        """Validate the diagram and report errors and warnings."""
        errors = []
        warnings = []
        nodes = self.model.nodes
        edges = self.model.edges

        # Check for startEvent
        has_start = any(n.type == "startEvent" for n in nodes.values())
        if not has_start:
            errors.append("ERROR: No startEvent found in the diagram.")

        # Check for endEvent
        has_end = any(n.type == "endEvent" for n in nodes.values())
        if not has_end:
            errors.append("ERROR: No endEvent found in the diagram.")

        # Check edges reference valid nodes
        for e in edges:
            if e.src not in nodes:
                errors.append(f"ERROR: Edge '{e.id}' references missing source node '{e.src}'.")
            if e.tgt not in nodes:
                errors.append(f"ERROR: Edge '{e.id}' references missing target node '{e.tgt}'.")

        # Check isolated nodes
        connected = set()
        for e in edges:
            connected.add(e.src)
            connected.add(e.tgt)
        for nid, n in nodes.items():
            if n.type in ("lane", "pool"):
                continue
            if nid not in connected:
                warnings.append(f"WARNING: Node '{n.text}' ({nid}) has no connections (isolated).")

        # Check gateways with < 2 outgoing sequence flows
        gateway_types = ("exclusiveGateway", "parallelGateway", "inclusiveGateway")
        for nid, n in nodes.items():
            if n.type in gateway_types:
                out_flows = [e for e in edges
                             if e.type == "sequenceFlow" and e.src == nid]
                if len(out_flows) < 2:
                    warnings.append(
                        f"WARNING: Gateway '{n.text}' ({nid}) has fewer than 2 outgoing "
                        f"sequence flows ({len(out_flows)} found)."
                    )

        if not errors and not warnings:
            messagebox.showinfo("Validation", "No issues found. Diagram looks valid!")
            return

        lines = []
        if errors:
            lines.append("ERRORS:")
            lines.extend(errors)
        if warnings:
            if lines:
                lines.append("")
            lines.append("WARNINGS:")
            lines.extend(warnings)

        messagebox.showwarning("Validation Results", "\n".join(lines))

    # -------- View toggles
    def toggle_view_bpmn(self):
        if self.view_mode == "json":
            raw = self.json_text.get("1.0", tk.END)
            try:
                data = json.loads(raw)
                self.model.load_json(data)
                self._flash_message("Loaded model from JSON view.")
            except Exception as e:
                stay = messagebox.askyesno(
                    "Invalid JSON",
                    f"Error parsing JSON:\n{e}\n\nStay in JSON view?",
                )
                if stay:
                    return
        self.json_frame.pack_forget()
        self.toolbar.pack(side=tk.LEFT, fill=tk.Y)
        self.canvas_area.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        self.prop_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.view_mode = "bpmn"
        self._multi_select.clear()
        self.redraw_all()
        self._update_window_title()

    def toggle_view_json(self):
        data = self.model.to_json()
        if self.current_file:
            data["file"] = os.path.basename(self.current_file)
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert("1.0", json.dumps(data, indent=2, ensure_ascii=False))
        self.canvas_area.pack_forget()
        self.toolbar.pack_forget()
        self.prop_panel.pack_forget()
        self.json_frame.pack(expand=True, fill=tk.BOTH)
        self.view_mode = "json"
        self._multi_select.clear()
        self._update_window_title()

    # -------- File ops (JSON)
    def new_diagram(self):
        if not messagebox.askyesno("New Diagram", "Clear the canvas and start a new diagram?"):
            return
        self.model = BPMNModel()
        self.current_file = None
        self._active_lane_id = None
        self._clear_lane_handles()
        self._dirty = False
        self._multi_select.clear()
        if self.view_mode == "bpmn":
            self.redraw_all()
        else:
            self.toggle_view_json()
        self._update_window_title()
        self._history.clear()
        self._redo.clear()
        self._push_history("init")

    def save_file(self):
        if not self.current_file:
            return self.save_json_as()
        try:
            data = self._data_from_current_view()
            with open(self.current_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._dirty = False
            self._update_window_title()
            self._flash_message(f"Saved: {self.current_file}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save: {e}")

    def save_json_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            data = self._data_from_current_view()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.current_file = path
            self._dirty = False
            self._update_window_title()
            self._flash_message(f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save: {e}")

    def _data_from_current_view(self):
        if self.view_mode == "json":
            raw = self.json_text.get("1.0", tk.END)
            data = json.loads(raw)
            if "processes" not in data:
                raise ValueError("JSON must contain a top-level 'processes' array.")
            return data
        else:
            data = self.model.to_json()
            if self.current_file:
                data["file"] = os.path.basename(self.current_file)
            return data

    def open_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.model.load_json(data)
            self.current_file = path
            self._active_lane_id = None
            self._clear_lane_handles()
            self._dirty = False
            self._multi_select.clear()
            if self.view_mode == "bpmn":
                self.redraw_all()
            else:
                self.toggle_view_json()
            self._flash_message(f"Opened: {path}")
            self._update_window_title()
            self._history.clear()
            self._redo.clear()
            self._push_history("open json")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open JSON: {e}")

    # -------- BPMN XML Import/Export
    def open_bpmn(self):
        path = filedialog.askopenfilename(filetypes=[("BPMN XML", "*.bpmn;*.xml")])
        if not path:
            return
        try:
            self._load_bpmn_file(path)
            self.current_file = path
            self._active_lane_id = None
            self._clear_lane_handles()
            self._dirty = False
            self._multi_select.clear()
            if self.view_mode == "bpmn":
                self.redraw_all()
            else:
                self.toggle_view_json()
            self._flash_message(f"Opened BPMN: {path}")
            self._update_window_title()
            self._history.clear()
            self._redo.clear()
            self._push_history("open bpmn")
        except Exception as e:
            messagebox.showerror("BPMN Import Error", f"Failed to import BPMN: {e}")

    def export_bpmn(self):
        path = filedialog.asksaveasfilename(defaultextension=".bpmn",
                                            filetypes=[("BPMN XML", "*.bpmn")])
        if not path:
            return
        try:
            if self.view_mode == "json":
                raw = self.json_text.get("1.0", tk.END)
                data = json.loads(raw)
                self.model.load_json(data)
            xml_string = self._model_to_bpmn_xml()
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml_string)
            self._flash_message(
                f"Exported BPMN XML: {path}  (Note: colours are only saved in JSON.)"
            )
        except Exception as e:
            messagebox.showerror("BPMN Export Error", f"Failed to export BPMN: {e}")

    # --- BPMN helpers (import)
    def _load_bpmn_file(self, path):
        for pfx, uri in self.NS.items():
            ET.register_namespace(pfx, uri)
        tree = ET.parse(path)
        root = tree.getroot()
        self.model = BPMNModel()
        q = self.q

        def findall(parent, tag, ns="bpmn"):
            return parent.findall(q(tag, ns))

        bounds_by_id = {}
        for shape in root.findall(f".//{q('BPMNShape', 'bpmndi')}"):
            be = shape.attrib.get("bpmnElement")
            b = shape.find(q("Bounds", "dc"))
            if be and b is not None:
                bounds_by_id[be] = (
                    float(b.attrib.get("x", "0")), float(b.attrib.get("y", "0")),
                    float(b.attrib.get("width", "120")), float(b.attrib.get("height", "60")),
                )

        def ensure_unique_id(original_id, taken):
            if original_id not in taken and original_id not in self.model.nodes:
                return original_id
            i = 2
            while True:
                cand = f"{original_id}__{i}"
                if cand not in taken and cand not in self.model.nodes:
                    return cand
                i += 1

        processes = findall(root, "process")
        if not processes:
            raise ValueError("No <bpmn:process> found.")
        global_id_map = {}

        def add_lane_recursive(lane_el, pid_map):
            lid_orig = lane_el.attrib.get("id")
            lname = lane_el.attrib.get("name", "Lane")
            x, y, w, h = bounds_by_id.get(lid_orig, (40.0, 20.0, 900.0, 150.0))
            lid = ensure_unique_id(lid_orig, pid_map.values())
            if lid != lid_orig:
                pid_map[lid_orig] = lid
                global_id_map[lid_orig] = lid
            self.model.add_node_with_id(lid, "lane", x, y, w, h, lname)
            for child in lane_el.findall(q("lane")):
                add_lane_recursive(child, pid_map)

        collab = root.find(q("collaboration"))
        if collab is not None:
            for part in collab.findall(q("participant")):
                pid_orig = part.attrib.get("id")
                pname = part.attrib.get("name", "Pool")
                x, y, w, h = bounds_by_id.get(pid_orig, (20.0, 10.0, 1100.0, 220.0))
                pool_id = (pid_orig if pid_orig not in self.model.nodes
                           else f"{pid_orig}__{len(self.model.nodes) + 1}")
                self.model.add_node_with_id(pool_id, "pool", x, y, w, h, pname)

        for proc in processes:
            pid_map = {}
            for laneset in findall(proc, "laneSet"):
                for lane in findall(laneset, "lane"):
                    add_lane_recursive(lane, pid_map)

            # Maps BPMN XML tag -> internal type
            node_tags = [
                ("startEvent", "startEvent"),
                ("endEvent", "endEvent"),
                ("exclusiveGateway", "exclusiveGateway"),
                ("parallelGateway", "parallelGateway"),
                ("inclusiveGateway", "inclusiveGateway"),
                ("intermediateCatchEvent", "intermediateEvent"),
                ("intermediateThrowEvent", "intermediateEvent"),
                ("task", "task"),
                ("userTask", "task"),
                ("serviceTask", "task"),
                ("manualTask", "task"),
                ("scriptTask", "task"),
                ("businessRuleTask", "task"),
                ("sendTask", "task"),
                ("receiveTask", "task"),
                ("callActivity", "task"),
            ]
            for tag, ntype in node_tags:
                for el in findall(proc, tag):
                    nid_orig = el.attrib.get("id")
                    nname = el.attrib.get("name", ntype)
                    x, y, w, h = bounds_by_id.get(nid_orig, (200.0, 100.0, 160.0, 80.0))
                    if ntype in ("startEvent", "endEvent", "intermediateEvent") and nid_orig not in bounds_by_id:
                        w = h = 60.0
                    if ntype in ("exclusiveGateway", "parallelGateway", "inclusiveGateway") and nid_orig not in bounds_by_id:
                        w = h = 80.0
                    nid = ensure_unique_id(nid_orig, pid_map.values())
                    if nid != nid_orig:
                        pid_map[nid_orig] = nid
                        global_id_map[nid_orig] = nid
                    node = self.model.add_node_with_id(nid, ntype, x, y, w, h, nname)
                    if ntype == "task":
                        node.subtype = tag  # preserve original BPMN task tag

            for sf in findall(proc, "sequenceFlow"):
                sid_orig = sf.attrib.get("id")
                src_orig = sf.attrib.get("sourceRef")
                tgt_orig = sf.attrib.get("targetRef")
                sname = sf.attrib.get("name", "")
                src = pid_map.get(src_orig, global_id_map.get(src_orig, src_orig))
                tgt = pid_map.get(tgt_orig, global_id_map.get(tgt_orig, tgt_orig))
                sid = ensure_unique_id(sid_orig, pid_map.values())
                if sid != sid_orig:
                    pid_map[sid_orig] = sid
                    global_id_map[sid_orig] = sid
                self.model.add_edge_with_id(sid, src, tgt, sname, etype="sequenceFlow")

            for laneset in findall(proc, "laneSet"):
                for lane in findall(laneset, "lane"):
                    lname = lane.attrib.get("name", lane.attrib.get("id", "Lane"))
                    for ref in lane.findall(q("flowNodeRef")):
                        orig_id = (ref.text or "").strip()
                        final_id = pid_map.get(orig_id, global_id_map.get(orig_id, orig_id))
                        if final_id in self.model.nodes:
                            self.model.nodes[final_id].lane_id = lname

        if collab is not None:
            for mf in collab.findall(q("messageFlow")):
                mid = mf.attrib.get("id")
                src = mf.attrib.get("sourceRef")
                tgt = mf.attrib.get("targetRef")
                name = mf.attrib.get("name", "")
                src_final = global_id_map.get(src, src)
                tgt_final = global_id_map.get(tgt, tgt)
                if src_final in self.model.nodes and tgt_final in self.model.nodes:
                    self.model.add_edge_with_id(mid, src_final, tgt_final, name, etype="messageFlow")
            for assoc in collab.findall(q("association")):
                aid = assoc.attrib.get("id")
                src = global_id_map.get(assoc.attrib.get("sourceRef"), assoc.attrib.get("sourceRef"))
                tgt = global_id_map.get(assoc.attrib.get("targetRef"), assoc.attrib.get("targetRef"))
                name = assoc.attrib.get("name", "")
                if src in self.model.nodes and tgt in self.model.nodes:
                    self.model.add_edge_with_id(aid, src, tgt, name, etype="association")

    def _model_to_bpmn_xml(self):
        for pfx, uri in self.NS.items():
            ET.register_namespace(pfx, uri)

        def E(tag, ns="bpmn", **attrs):
            el = ET.Element(f"{{{self.NS[ns]}}}{tag}")
            for k, v in attrs.items():
                if v is None:
                    continue
                el.set(k, str(v))
            return el

        defs = E("definitions")
        defs.attrib["id"] = "Defs_1"
        process = E("process", id="Process_1",
                     name=self.model.process_name or "Process_1", isExecutable="false")
        defs.append(process)

        lane_nodes = [n for n in self.model.nodes.values() if n.type == "lane"]
        if lane_nodes:
            lane_set = E("laneSet", id="LaneSet_1")
            process.append(lane_set)

            def inside(node, lane):
                return (lane.x <= node.x and lane.y <= node.y and
                        (node.x + node.w) <= (lane.x + lane.w) and
                        (node.y + node.h) <= (lane.y + lane.h))

            for ln in lane_nodes:
                lane = E("lane", id=ln.id, name=(ln.text or "Lane"))
                lane_set.append(lane)
                for n in self.model.nodes.values():
                    if n.type in ("lane", "pool"):
                        continue
                    if (n.lane_id and n.lane_id == (ln.text or "Lane")) or inside(n, ln):
                        ET.SubElement(lane, self.q("flowNodeRef")).text = n.id

        def node_xml(node):
            name_attr = (node.text or node.type or "").strip()
            if node.type == "startEvent":
                el = E("startEvent", id=node.id, name=name_attr)
            elif node.type == "endEvent":
                el = E("endEvent", id=node.id, name=name_attr)
            elif node.type == "exclusiveGateway":
                el = E("exclusiveGateway", id=node.id, name=name_attr)
            elif node.type == "parallelGateway":
                el = E("parallelGateway", id=node.id, name=name_attr)
            elif node.type == "inclusiveGateway":
                el = E("inclusiveGateway", id=node.id, name=name_attr)
            elif node.type == "intermediateEvent":
                el = E("intermediateCatchEvent", id=node.id, name=name_attr)
            elif node.type == "task":
                task_tag = node.subtype if node.subtype else "userTask"
                el = E(task_tag, id=node.id, name=name_attr)
            else:
                return None
            for inc in filter(None, node.incoming):
                ET.SubElement(el, self.q("incoming")).text = str(inc)
            for out in filter(None, node.outgoing):
                ET.SubElement(el, self.q("outgoing")).text = str(out)
            return el

        for n in self.model.nodes.values():
            if n.type in ("lane", "pool"):
                continue
            el = node_xml(n)
            if el is not None:
                process.append(el)

        for e in self.model.edges:
            if e.type != "sequenceFlow":
                continue
            sf = E("sequenceFlow", id=e.id, sourceRef=e.src, targetRef=e.tgt)
            if e.name:
                sf.attrib["name"] = str(e.name)
            process.append(sf)

        has_msg = any(e.type == "messageFlow" for e in self.model.edges)
        has_pool = any(n.type == "pool" for n in self.model.nodes.values())
        if has_msg or has_pool:
            collab = E("collaboration", id="Collab_1")
            defs.append(collab)
            if has_pool:
                for n in self.model.nodes.values():
                    if n.type == "pool":
                        collab.append(E("participant", id=n.id,
                                        name=(n.text or "Pool"), processRef="Process_1"))
            for e in self.model.edges:
                if e.type == "messageFlow":
                    collab.append(E("messageFlow", id=e.id,
                                    sourceRef=e.src, targetRef=e.tgt, name=e.name or ""))

        bpmndi = E("BPMNDiagram", "bpmndi", id="BPMNDiagram_1")
        defs.append(bpmndi)
        plane = E("BPMNPlane", "bpmndi", id="BPMNPlane_1", bpmnElement="Process_1")
        bpmndi.append(plane)

        def bounds(parent, x, y, w, h):
            parent.append(ET.Element(
                f"{{{self.NS['dc']}}}Bounds",
                {"x": str(x), "y": str(y), "width": str(w), "height": str(h)},
            ))

        for n in self.model.nodes.values():
            shape = E("BPMNShape", "bpmndi", id=f"{n.id}_di", bpmnElement=n.id)
            plane.append(shape)
            bounds(shape, n.x, n.y, n.w, n.h)

        for e in self.model.edges:
            if e.src not in self.model.nodes or e.tgt not in self.model.nodes:
                continue
            s = self.model.nodes[e.src]
            t = self.model.nodes[e.tgt]
            # Use orthogonal waypoints for XML export (model coords)
            model_pts = self._edge_waypoints(s, t)
            edge_el = E("BPMNEdge", "bpmndi", id=f"{e.id}_di", bpmnElement=e.id)
            plane.append(edge_el)
            for idx in range(0, len(model_pts), 2):
                ET.SubElement(edge_el, self.q("waypoint", "di"),
                              {"x": str(model_pts[idx]), "y": str(model_pts[idx + 1])})

        xml_bytes = ET.tostring(defs, encoding="utf-8", xml_declaration=True)
        return xml_bytes.decode("utf-8")

    # -------- PNG Export
    def export_png(self):
        ps_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PostScript", "*.ps")],
        )
        if not ps_path:
            return
        tmp_ps = ps_path if ps_path.lower().endswith(".ps") else ps_path + ".ps"
        try:
            was_json = (self.view_mode == "json")
            if was_json:
                self.json_frame.pack_forget()
                self.toolbar.pack(side=tk.LEFT, fill=tk.Y)
                self.canvas_area.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
                self.view_mode = "bpmn"
                self.redraw_all()
            self.update_idletasks()
            self.canvas.postscript(file=tmp_ps, colormode="color")
            if ps_path.lower().endswith(".ps"):
                self._flash_message(f"Exported PostScript: {tmp_ps}")
            else:
                if not PIL_AVAILABLE:
                    messagebox.showwarning(
                        "Pillow not available",
                        "Pillow is not installed; saved PostScript instead.\n"
                        "Install Pillow and Ghostscript to enable PNG export.",
                    )
                    self._flash_message(f"Saved PostScript: {tmp_ps}")
                else:
                    try:
                        img = Image.open(tmp_ps)
                        img.save(ps_path, "PNG")
                    except Exception as gs_err:
                        messagebox.showwarning(
                            "PNG conversion failed",
                            "Could not convert PostScript to PNG.\n"
                            "Ghostscript may not be installed on your system.\n\n"
                            f"Saved PostScript instead: {tmp_ps}\n\nError: {gs_err}",
                        )
                        self._flash_message(f"Saved PostScript: {tmp_ps}")
                        if was_json:
                            self.toggle_view_json()
                        return
                    try:
                        os.remove(tmp_ps)
                    except Exception:
                        pass
                    self._flash_message(f"Exported PNG: {ps_path}")
            if was_json:
                self.toggle_view_json()
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export: {e}")

    # -------- Undo/Redo internals
    def _snapshot(self):
        return json.loads(json.dumps(self.model.to_json()))

    def _load_snapshot(self, snap):
        self.model.load_json(snap)
        self._multi_select.clear()
        if self.view_mode == "bpmn":
            self.redraw_all()
        else:
            self.toggle_view_json()

    def _push_history(self, why=""):
        self._history.append(self._snapshot())
        if len(self._history) > self._max_history + 1:
            self._history.pop(0)
        self._redo.clear()
        if why not in ("init", "open json", "open bpmn"):
            self._dirty = True
        self._update_window_title()

    def cmd_undo(self):
        if len(self._history) <= 1:
            self._flash_message("Nothing to undo")
            return
        last = self._history.pop()
        self._redo.append(last)
        prev = self._history[-1]
        self._load_snapshot(prev)
        self._dirty = True
        self._update_window_title()
        self._flash_message("Undo")

    def cmd_redo(self):
        if not self._redo:
            self._flash_message("Nothing to redo")
            return
        nxt = self._redo.pop()
        self._history.append(nxt)
        self._load_snapshot(nxt)
        self._dirty = True
        self._update_window_title()
        self._flash_message("Redo")

    # -------- Misc
    def _flash_message(self, msg):
        self.status_bar.config(text=msg)

    def _update_window_title(self):
        fname = os.path.basename(self.current_file) if self.current_file else "Untitled.json"
        mode = "BPMN" if self.view_mode == "bpmn" else "JSON"
        dirty = " *" if self._dirty else ""
        self.title(f"BPMN Studio – [{fname}{dirty}] – {mode} View")


if __name__ == "__main__":
    app = BPMNStudio()
    app.mainloop()
