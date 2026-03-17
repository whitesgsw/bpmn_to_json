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

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

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
        self.annotation = None

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
        elif self.type == "annotation":
            self.fill = self.fill or "#fffde7"
            self.outline = self.outline or "#fbbf24"
            self.text_color = self.text_color or "#374151"
        elif self.type == "externalPool":
            self.fill = self.fill or "#f3f4f6"
            self.outline = self.outline or "#9ca3af"
            self.text_color = self.text_color or "#6b7280"
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
            "annotation": self.annotation or None,
        }


class Edge:
    def __init__(self, eid, src, tgt, label=None, etype="sequenceFlow"):
        self.id = eid
        self.type = etype  # 'sequenceFlow' | 'messageFlow' | 'association'
        self.src = src
        self.tgt = tgt
        self.name = label or ""
        self.condition = None
        self.annotation = None

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "from": self.src,
            "to": self.tgt,
            "name": self.name,
            "condition": self.condition,
            "annotation": self.annotation or None,
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
    "annotation": "Annotation",
    "externalPool": "ExtPool",
}

_CONFIG_FILE = os.path.expanduser("~/.bpmn_studio_config.json")


class BPMNModel:
    def __init__(self, process_name="Process_1"):
        self.processes = [{"id": "Process_1", "name": process_name, "nodes": {}, "edges": []}]
        self.active_process_idx = 0
        self.links = []
        self._counter = 1

    @property
    def process_name(self):
        return self.processes[self.active_process_idx]["name"]

    @process_name.setter
    def process_name(self, value):
        self.processes[self.active_process_idx]["name"] = value

    @property
    def nodes(self):
        return self.processes[self.active_process_idx]["nodes"]

    @property
    def edges(self):
        return self.processes[self.active_process_idx]["edges"]

    def add_process(self, name=None):
        idx = len(self.processes) + 1
        pid = f"Process_{idx}"
        name = name or f"Process {idx}"
        self.processes.append({"id": pid, "name": name, "nodes": {}, "edges": []})
        return len(self.processes) - 1

    def delete_process(self, idx):
        if len(self.processes) <= 1:
            return False
        self.processes.pop(idx)
        if self.active_process_idx >= len(self.processes):
            self.active_process_idx = len(self.processes) - 1
        return True

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
        elif ntype == "annotation":
            w, h = 160, 60
            text = "Note"
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
        self.edges[:] = kept

    def to_json(self):
        return {
            "definitions_id": "Defs_1",
            "processes": [
                {
                    "id": p.get("id", f"Process_{i+1}"),
                    "name": p.get("name", f"Process {i+1}"),
                    "nodes": {nid: n.to_dict() for nid, n in p["nodes"].items()},
                    "edges": [e.to_dict() for e in p["edges"]],
                    "di": {"shapes": {}, "edges": {}},
                }
                for i, p in enumerate(self.processes)
            ],
            "links": self.links,
            "collaboration": {"messageFlows": []},
        }

    def load_json(self, data):
        self.processes = []
        self.active_process_idx = 0
        self.links = data.get("links", [])
        self._counter = 1
        procs = data.get("processes", [])
        if not procs:
            self.processes = [{"id": "Process_1", "name": "Process 1", "nodes": {}, "edges": []}]
            return
        max_num = 0
        for p in procs:
            proc = {"id": p.get("id", "Process_1"), "name": p.get("name", "Process 1"),
                    "nodes": {}, "edges": []}
            for nid, nd in p.get("nodes", {}).items():
                style = nd.get("style", {}) or {}
                node = Node(
                    nid, nd.get("type"), nd.get("x"), nd.get("y"),
                    nd.get("w", 120), nd.get("h", 60),
                    text=(nd.get("name") or nd.get("type") or "Node"),
                    lane_id=nd.get("lane"),
                    fill=style.get("fill"), outline=style.get("outline"),
                    text_color=style.get("text"),
                )
                node.subtype = nd.get("subtype")
                node.annotation = nd.get("annotation") or None
                node.ensure_defaults_for_type()
                node.incoming = [str(x) for x in (nd.get("incoming", []) or []) if x is not None]
                node.outgoing = [str(x) for x in (nd.get("outgoing", []) or []) if x is not None]
                node.next = [str(x) for x in (nd.get("next", []) or []) if x is not None]
                node.prev = [str(x) for x in (nd.get("prev", []) or []) if x is not None]
                proc["nodes"][nid] = node
                parts = nid.rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    max_num = max(max_num, int(parts[1]))
            for ed in p.get("edges", []):
                e = Edge(ed.get("id"), ed.get("from"), ed.get("to"), ed.get("name"),
                         etype=ed.get("type", "sequenceFlow"))
                e.condition = ed.get("condition")
                e.annotation = ed.get("annotation") or None
                proc["edges"].append(e)
                if e.id:
                    parts = e.id.rsplit("_", 1)
                    if len(parts) == 2 and parts[1].isdigit():
                        max_num = max(max_num, int(parts[1]))
            self.processes.append(proc)
        self._counter = max_num + 1


# ----------------------------- Markdown → Tkinter renderer -------------------

class _TkMarkdownRenderer:
    """Renders a mistune AST directly into a Tkinter Text widget."""

    def __init__(self, widget):
        self._d = widget

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def render(self, tokens):
        for token in tokens:
            self._block(token)

    # ------------------------------------------------------------------
    # Block-level tokens
    # ------------------------------------------------------------------
    def _block(self, token):
        t = token.get("type")
        if t == "heading":
            level = token.get("attrs", {}).get("level", 1)
            tag = f"ai_h{min(level, 3)}"
            self._d.insert("end", self._collect(token.get("children", [])) + "\n", tag)
        elif t == "paragraph":
            self._inline_children(token.get("children", []))
            self._d.insert("end", "\n\n", "ai_text")
        elif t == "block_code":
            self._d.insert("end", token.get("raw", "") + "\n\n", "ai_code_block")
        elif t == "thematic_break":
            self._d.insert("end", "─" * 48 + "\n", "ai_hr")
        elif t == "list":
            ordered = token.get("attrs", {}).get("ordered", False)
            for idx, item in enumerate(token.get("children", [])):
                if ordered:
                    self._d.insert("end", f"  {idx + 1}. ", "ai_bullet_marker")
                else:
                    self._d.insert("end", "  • ", "ai_bullet_marker")
                for child in item.get("children", []):
                    ct = child["type"]
                    if ct in ("paragraph", "block_text"):
                        # block_text = tight list, paragraph = loose list
                        self._inline_children(child.get("children", []))
                    elif ct == "text":
                        self._d.insert("end", child.get("raw", ""), "ai_text")
                    else:
                        self._block(child)
                self._d.insert("end", "\n", "ai_text")
            self._d.insert("end", "\n", "ai_text")
        elif t == "table":
            self._table(token)
        elif t in ("blank_line", "newline"):
            self._d.insert("end", "\n", "ai_text")
        elif t == "block_quote":
            for child in token.get("children", []):
                self._block(child)

    # ------------------------------------------------------------------
    # Inline tokens
    # ------------------------------------------------------------------
    def _inline_children(self, children):
        for token in children:
            self._inline(token)

    def _inline(self, token):
        t = token.get("type")
        if t == "text":
            self._d.insert("end", token.get("raw", ""), "ai_text")
        elif t == "strong":
            self._d.insert("end", self._collect(token.get("children", [])), "ai_bold")
        elif t == "emphasis":
            self._d.insert("end", self._collect(token.get("children", [])), "ai_italic")
        elif t == "codespan":
            self._d.insert("end", token.get("raw", ""), "ai_inline_code")
        elif t in ("softlinebreak", "linebreak"):
            self._d.insert("end", "\n", "ai_text")
        elif "children" in token:
            self._inline_children(token["children"])
        else:
            raw = token.get("raw", "")
            if raw:
                self._d.insert("end", raw, "ai_text")

    def _collect(self, tokens):
        """Recursively extract plain text from a list of inline tokens."""
        parts = []
        for token in tokens:
            if token.get("type") in ("text", "codespan"):
                parts.append(token.get("raw", ""))
            elif token.get("type") in ("softlinebreak", "linebreak"):
                parts.append("\n")
            elif "children" in token:
                parts.append(self._collect(token["children"]))
        return "".join(parts)

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------
    def _table(self, token):
        head_rows, body_rows = [], []
        for child in token.get("children", []):
            if child["type"] == "table_head":
                for row in child.get("children", []):
                    head_rows.append(self._extract_cells(row))
            elif child["type"] == "table_body":
                for row in child.get("children", []):
                    body_rows.append(self._extract_cells(row))

        all_rows = head_rows + body_rows
        if not all_rows:
            return

        col_count = max(len(r) for r in all_rows)
        col_widths = [0] * col_count
        for row in all_rows:
            for j, (plain, _) in enumerate(row):
                col_widths[j] = max(col_widths[j], len(plain))

        def insert_row(row, tag):
            self._d.insert("end", " ", tag)
            for j in range(col_count):
                plain, children = row[j] if j < len(row) else ("", [])
                self._inline_children(children)
                pad = col_widths[j] - len(plain)
                if pad > 0:
                    self._d.insert("end", " " * pad, tag)
                if j < col_count - 1:
                    self._d.insert("end", " │ ", "ai_table_div")
            self._d.insert("end", "\n", tag)

        def insert_divider():
            segs = ["─" * col_widths[j] for j in range(col_count)]
            self._d.insert("end", " " + "─┼─".join(segs) + "\n", "ai_table_div")

        for row in head_rows:
            insert_row(row, "ai_table_header")
        insert_divider()
        for row in body_rows:
            insert_row(row, "ai_table_cell")
        self._d.insert("end", "\n", "ai_text")

    def _extract_cells(self, row_token):
        """Return [(plain_text, children_tokens), ...] for each cell in a row."""
        cells = []
        for cell in row_token.get("children", []):
            children = cell.get("children", [])
            cells.append((self._collect(children), children))
        return cells


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
        self._dragging_pool = None
        self._pool_handle_to_info = {}
        self._resizing_pool = None
        self._active_pool_id = None
        self._panning = False

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

        # Recent files
        self._recent_files = []
        self._recent_menu = None

        # Minimap
        self._minimap_visible = tk.BooleanVar(value=True)

        # Chat / AI assistant state
        self._chat_history = []
        self._chat_mode = tk.StringVar(value="process")
        self._claude_api_key = ""
        self._repo_folder = ""
        self._chat_streaming = False
        self._chat_tab_btns = {}

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
        self._ctx_menu.add_command(label="Remove Link", command=self._ctx_remove_link)
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
        self.bind_all("<Control-f>", lambda e: self._show_search())

        self._update_window_title()
        self._push_history("init")
        self._load_recent_files()
        self._update_process_tabs()

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
        self._recent_menu = tk.Menu(fm, tearoff=0)
        fm.add_cascade(label="Recent Files", menu=self._recent_menu)
        fm.add_separator()
        fm.add_command(label="Save", command=self.save_file)
        fm.add_command(label="Save As…", command=self.save_json_as)
        fm.add_separator()
        fm.add_command(label="Export BPMN XML…", command=self.export_bpmn)
        fm.add_command(label="Export PNG…", command=self.export_png)
        fm.add_command(label="Link External Process…", command=self.link_external_process)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.destroy)
        self.menubar.add_cascade(label="File", menu=fm)

        em = tk.Menu(self.menubar, tearoff=0)
        em.add_command(label="Copy", command=self.cmd_copy)
        em.add_command(label="Paste", command=self.cmd_paste)
        em.add_command(label="Select All", command=self.cmd_select_all)
        em.add_command(label="Find…", command=self._show_search)
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
        vm.add_checkbutton(label="Show Minimap", variable=self._minimap_visible,
                           command=self._toggle_minimap)
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

    # -------- Recent files
    def _load_recent_files(self):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self._recent_files = cfg.get("recent_files", [])
            self._claude_api_key = cfg.get("claude_api_key", "")
            self._repo_folder = cfg.get("repo_folder", "")
        except Exception:
            self._recent_files = []
        self._rebuild_recent_menu()

    def _save_recent_files(self):
        try:
            cfg = {}
            try:
                with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
            cfg["recent_files"] = self._recent_files
            cfg["claude_api_key"] = self._claude_api_key
            cfg["repo_folder"] = self._repo_folder
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _add_recent_file(self, path):
        path = os.path.abspath(path)
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:8]
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        if self._recent_menu is None:
            return
        self._recent_menu.delete(0, tk.END)
        if not self._recent_files:
            self._recent_menu.add_command(label="(no recent files)", state=tk.DISABLED)
            return
        for path in self._recent_files:
            label = os.path.basename(path)
            if os.path.exists(path):
                self._recent_menu.add_command(
                    label=label,
                    command=lambda p=path: self._open_recent(p),
                )
            else:
                self._recent_menu.add_command(
                    label=f"{label}  [missing]",
                    state=tk.DISABLED,
                )
        self._recent_menu.add_separator()
        self._recent_menu.add_command(label="Clear Recent Files",
                                      command=self._clear_recent_files)

    def _clear_recent_files(self):
        self._recent_files = []
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _open_recent(self, path):
        if path.lower().endswith(".json"):
            self._do_open_json(path)
        else:
            self._flash_message(f"Cannot open: {path}")

    # -------- Process tabs
    def _update_process_tabs(self):
        for w in self._tab_bar.winfo_children():
            w.destroy()
        for idx, proc in enumerate(self.model.processes):
            active = (idx == self.model.active_process_idx)
            bg = "#ffffff" if active else "#d1d5db"
            btn = tk.Button(
                self._tab_bar, text=proc["name"],
                bg=bg, relief="flat", padx=10, pady=4,
                command=lambda i=idx: self._switch_process(i),
            )
            btn.pack(side=tk.LEFT, padx=1, pady=2)
            btn.bind("<Button-3>", lambda e, i=idx: self._tab_context_menu(e, i))
        add_btn = tk.Button(self._tab_bar, text="+", bg="#e5e7eb", relief="flat",
                            padx=8, pady=4, command=self._add_process)
        add_btn.pack(side=tk.LEFT, padx=2, pady=2)

    def _switch_process(self, idx):
        self.model.active_process_idx = idx
        self._active_lane_id = None
        self._clear_lane_handles()
        self._active_pool_id = None
        self._clear_pool_handles()
        self._multi_select.clear()
        self._selected_item = None
        self.redraw_all()
        self._update_process_tabs()

    def _add_process(self):
        name = simpledialog.askstring("New Process", "Process name:", parent=self)
        if not name:
            return
        idx = self.model.add_process(name)
        self._switch_process(idx)
        self._push_history("add process")

    def _tab_context_menu(self, event, idx):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Rename", command=lambda: self._rename_process(idx))
        menu.add_command(label="Delete", command=lambda: self._delete_process(idx))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _rename_process(self, idx):
        old = self.model.processes[idx]["name"]
        new = simpledialog.askstring("Rename Process", "New name:", initialvalue=old, parent=self)
        if new and new.strip():
            self.model.processes[idx]["name"] = new.strip()
            self._update_process_tabs()
            self._push_history("rename process")

    def _delete_process(self, idx):
        if not messagebox.askyesno("Delete Process",
                                   f"Delete process '{self.model.processes[idx]['name']}'?"):
            return
        if not self.model.delete_process(idx):
            messagebox.showwarning("Cannot Delete", "Cannot delete the only process.")
            return
        self._switch_process(self.model.active_process_idx)
        self._push_history("delete process")

    # -------- Search / filter
    def _show_search(self):
        self._search_frame.pack(side=tk.TOP, fill=tk.X, before=self.canvas)
        self._search_entry.focus_set()

    def _hide_search(self):
        self._search_frame.pack_forget()
        self.canvas.delete("search_highlight")
        self._search_matches = []
        self._search_count_lbl.config(text="")

    def _update_search_highlights(self):
        self.canvas.delete("search_highlight")
        self._search_matches = []
        term = self._search_var.get().strip().lower()
        if not term:
            self._search_count_lbl.config(text="")
            return
        z = self._zoom
        for nid, n in self.model.nodes.items():
            if n.type in ("lane", "pool"):
                continue
            if term in (n.text or "").lower():
                self._search_matches.append(nid)
                pad = 4
                self.canvas.create_rectangle(
                    n.x * z - pad, n.y * z - pad,
                    (n.x + n.w) * z + pad, (n.y + n.h) * z + pad,
                    outline="#facc15", width=3, tags="search_highlight",
                )
        self.canvas.tag_raise("search_highlight")
        self.canvas.tag_raise("node")
        count = len(self._search_matches)
        self._search_count_lbl.config(text=f"{count} match{'es' if count != 1 else ''}")
        self._search_match_idx = 0

    def _search_next(self):
        if not self._search_matches:
            return
        self._search_match_idx = (self._search_match_idx + 1) % len(self._search_matches)
        self._scroll_to_node(self._search_matches[self._search_match_idx])

    def _search_prev(self):
        if not self._search_matches:
            return
        self._search_match_idx = (self._search_match_idx - 1) % len(self._search_matches)
        self._scroll_to_node(self._search_matches[self._search_match_idx])

    def _scroll_to_node(self, nid):
        if nid not in self.model.nodes:
            return
        n = self.model.nodes[nid]
        z = self._zoom
        cx = (n.x + n.w / 2) * z
        cy = (n.y + n.h / 2) * z
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        x1, y1, x2, y2 = bbox
        total_w = x2 - x1
        total_h = y2 - y1
        if total_w > 0:
            self.canvas.xview_moveto((cx - x1 - 200) / total_w)
        if total_h > 0:
            self.canvas.yview_moveto((cy - y1 - 150) / total_h)

    # -------- Minimap
    def _toggle_minimap(self):
        if self._minimap_visible.get():
            self._minimap.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)
        else:
            self._minimap.place_forget()

    def _refresh_minimap(self):
        if not self._minimap_visible.get():
            return
        self._minimap.delete("all")
        mw, mh = 160, 100
        # Collect all node bounding boxes
        nodes = [n for n in self.model.nodes.values() if n.type not in ("lane",)]
        if not nodes:
            return
        min_x = min(n.x for n in nodes)
        min_y = min(n.y for n in nodes)
        max_x = max(n.x + n.w for n in nodes)
        max_y = max(n.y + n.h for n in nodes)
        span_x = max(max_x - min_x, 1)
        span_y = max(max_y - min_y, 1)
        pad = 10
        scale_x = (mw - pad * 2) / span_x
        scale_y = (mh - pad * 2) / span_y
        scale = min(scale_x, scale_y)
        def to_mm(nx, ny):
            return (nx - min_x) * scale + pad, (ny - min_y) * scale + pad
        for n in nodes:
            mx1, my1 = to_mm(n.x, n.y)
            mx2, my2 = to_mm(n.x + n.w, n.y + n.h)
            self._minimap.create_rectangle(mx1, my1, mx2, my2,
                                            fill=n.fill or "#ffffff",
                                            outline=n.outline or "#374151", width=1)
        # Viewport indicator
        try:
            x1f = self.canvas.xview()[0]
            x2f = self.canvas.xview()[1]
            y1f = self.canvas.yview()[0]
            y2f = self.canvas.yview()[1]
            bbox = self.canvas.bbox("all")
            if bbox:
                bx1, by1, bx2, by2 = bbox
                tw = bx2 - bx1
                th = by2 - by1
                vx1 = (bx1 + x1f * tw - min_x * scale) + pad
                vy1 = (by1 + y1f * th - min_y * scale) + pad
                vx2 = (bx1 + x2f * tw - min_x * scale) + pad
                vy2 = (by1 + y2f * th - min_y * scale) + pad
                self._minimap.create_rectangle(vx1, vy1, vx2, vy2,
                                                outline="#2563eb", width=1,
                                                dash=(3, 2))
        except Exception:
            pass

    def _minimap_click(self, event):
        mw, mh = 160, 100
        nodes = [n for n in self.model.nodes.values() if n.type not in ("lane",)]
        if not nodes:
            return
        min_x = min(n.x for n in nodes)
        min_y = min(n.y for n in nodes)
        max_x = max(n.x + n.w for n in nodes)
        max_y = max(n.y + n.h for n in nodes)
        span_x = max(max_x - min_x, 1)
        span_y = max(max_y - min_y, 1)
        pad = 10
        scale = min((mw - pad * 2) / span_x, (mh - pad * 2) / span_y)
        model_x = (event.x - pad) / scale + min_x
        model_y = (event.y - pad) / scale + min_y
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        bx1, by1, bx2, by2 = bbox
        tw = max(bx2 - bx1, 1)
        th = max(by2 - by1, 1)
        canvas_x = model_x * self._zoom
        canvas_y = model_y * self._zoom
        self.canvas.xview_moveto(max(0, (canvas_x - bx1 - 200) / tw))
        self.canvas.yview_moveto(max(0, (canvas_y - by1 - 150) / th))
        self._refresh_minimap()

    # -------- Cross-file process linking
    def link_external_process(self):
        path = filedialog.askopenfilename(
            title="Select BPMN Studio JSON file to link",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            procs = data.get("processes", [])
            if not procs:
                messagebox.showwarning("Link External", "No processes found in selected file.")
                return
            for proc in procs:
                pid = proc.get("id", "Process_1")
                pname = proc.get("name", "Process")
                nid = self.model.gen_id("ExtPool")
                label = f"{os.path.basename(path)}: {pname}"
                node = self.model.add_node_with_id(nid, "externalPool", 50, 50, 300, 80, label)
                self.model.links.append({"file": path, "process": pid, "node_id": nid})
            self.redraw_all()
            self._update_process_tabs()
            self._push_history("link external process")
            self._flash_message(f"Linked: {os.path.basename(path)}")
        except Exception as ex:
            messagebox.showerror("Link Error", f"Failed to link file: {ex}")

    def _ctx_remove_link(self):
        if not self._selected_item:
            return
        nid = self.item_to_node_id(self._selected_item)
        if not nid and self._selected_item in self._label_by_item:
            nid, _ = self._label_by_item[self._selected_item]
        if not nid or nid not in self.model.nodes:
            return
        if self.model.nodes[nid].type != "externalPool":
            self._flash_message("Selected item is not an external link.")
            return
        self.model.links = [l for l in self.model.links if l.get("node_id") != nid]
        self.model.delete_node(nid)
        self._selected_item = None
        self.redraw_all()
        self._push_history("remove link")

    def _load_external_links(self):
        """Reload externalPool nodes for all links after loading a file."""
        # Remove stale externalPool nodes first
        stale = [nid for nid, n in self.model.nodes.items() if n.type == "externalPool"]
        for nid in stale:
            del self.model.nodes[nid]
        for link in self.model.links:
            path = link.get("file", "")
            pid = link.get("process", "")
            nid = link.get("node_id", self.model.gen_id("ExtPool"))
            link["node_id"] = nid
            label = f"{os.path.basename(path)}: {pid}"
            if not os.path.exists(path):
                label += " [missing]"
            else:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    for p in d.get("processes", []):
                        if p.get("id") == pid:
                            label = f"{os.path.basename(path)}: {p.get('name', pid)}"
                            break
                except Exception:
                    label += " [error]"
            self.model.add_node_with_id(nid, "externalPool", 50, 50, 300, 80, label)

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

        # Process tab bar
        self._tab_bar = tk.Frame(self.canvas_area, bg="#e5e7eb", height=30)
        self._tab_bar.pack(side=tk.TOP, fill=tk.X)
        self._tab_bar.pack_propagate(False)

        # Search bar (hidden by default)
        self._search_frame = tk.Frame(self.canvas_area, bg="#fef9c3", pady=2)
        self._search_var = tk.StringVar()
        self._search_matches = []
        self._search_match_idx = 0
        tk.Label(self._search_frame, text="Find:", bg="#fef9c3").pack(side=tk.LEFT, padx=4)
        self._search_entry = tk.Entry(self._search_frame, textvariable=self._search_var, width=30)
        self._search_entry.pack(side=tk.LEFT, padx=2)
        self._search_entry.bind("<Return>", lambda e: self._search_next())
        self._search_entry.bind("<Escape>", lambda e: self._hide_search())
        self._search_count_lbl = tk.Label(self._search_frame, text="", bg="#fef9c3", fg="#6b7280")
        self._search_count_lbl.pack(side=tk.LEFT, padx=4)
        tk.Button(self._search_frame, text="▲", command=self._search_prev, width=2).pack(side=tk.LEFT)
        tk.Button(self._search_frame, text="▼", command=self._search_next, width=2).pack(side=tk.LEFT)
        tk.Button(self._search_frame, text="✕", command=self._hide_search, width=2).pack(side=tk.LEFT, padx=4)
        self._search_var.trace_add("write", lambda *_: self._update_search_highlights())
        # search bar starts hidden — do NOT pack it here

        # Vertical PanedWindow: canvas on top (~80%), chat on bottom (~20%)
        self._canvas_chat_pane = tk.PanedWindow(
            self.canvas_area, orient=tk.VERTICAL,
            sashwidth=6, sashrelief="raised", bg="#e5e7eb",
        )
        self._canvas_chat_pane.pack(side=tk.TOP, expand=True, fill=tk.BOTH)

        # Top pane: canvas + scrollbars
        canvas_wrap = tk.Frame(self._canvas_chat_pane, bg=self.BG)
        self._canvas_chat_pane.add(canvas_wrap, stretch="always", minsize=150)

        self.v_scroll = tk.Scrollbar(canvas_wrap, orient=tk.VERTICAL)
        self.h_scroll = tk.Scrollbar(canvas_wrap, orient=tk.HORIZONTAL)
        self.canvas = tk.Canvas(canvas_wrap, bg="#ffffff", highlightthickness=0,
                                xscrollcommand=self.h_scroll.set,
                                yscrollcommand=self.v_scroll.set)
        self.canvas.pack(side=tk.TOP, expand=True, fill=tk.BOTH)
        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        # Minimap overlay
        self._minimap = tk.Canvas(self.canvas, width=160, height=100,
                                   bg="#f8fafc", highlightthickness=1,
                                   highlightbackground="#94a3b8")
        self._minimap.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)
        self._minimap.bind("<Button-1>", self._minimap_click)
        tk.Label(self._minimap, text="Map", bg="#f8fafc", fg="#94a3b8",
                 font=("Arial", 7)).place(x=2, y=2)

        # Bottom pane: Claude AI chat panel
        chat_frame = tk.Frame(self._canvas_chat_pane, bg="#0f172a")
        self._canvas_chat_pane.add(chat_frame, stretch="never", minsize=120)
        self._build_chat_panel(chat_frame)

        # Set initial sash position (80/20 split) once window is rendered
        self.after(80, self._set_initial_chat_sash)

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

    # -------- Chat panel (Claude AI assistant)

    def _set_initial_chat_sash(self):
        h = self._canvas_chat_pane.winfo_height()
        if h > 1:
            self._canvas_chat_pane.sash_place(0, 0, int(h * 0.65))
        else:
            self.after(100, self._set_initial_chat_sash)

    def _build_chat_panel(self, parent):
        """Build the Claude AI chat interface in the bottom pane."""
        # Header / tab bar
        header = tk.Frame(parent, bg="#0f172a", height=36)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        for mode, label in (("process", "Current Process"), ("repository", "Process Repository")):
            btn = tk.Button(
                header, text=label, relief="flat", font=("Arial", 9, "bold"),
                padx=12, pady=0, cursor="hand2",
                command=lambda m=mode: self._set_chat_mode(m),
            )
            btn.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))
            self._chat_tab_btns[mode] = btn

        tk.Button(header, text="Clear", relief="flat", bg="#0f172a", fg="#64748b",
                  font=("Arial", 8), padx=6, cursor="hand2",
                  command=self._clear_chat).pack(side=tk.RIGHT, padx=2)
        tk.Button(header, text="API Key…", relief="flat", bg="#0f172a", fg="#64748b",
                  font=("Arial", 8), padx=6, cursor="hand2",
                  command=self._set_api_key).pack(side=tk.RIGHT, padx=2)
        tk.Button(header, text="Set Folder…", relief="flat", bg="#0f172a", fg="#64748b",
                  font=("Arial", 8), padx=6, cursor="hand2",
                  command=self._pick_repo_folder).pack(side=tk.RIGHT, padx=2)

        self._refresh_chat_tabs()

        # Input bar — must be packed BEFORE the expanding display area
        input_bar = tk.Frame(parent, bg="#0f172a", pady=6)
        input_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._chat_input = tk.Text(
            input_bar, height=2, bg="#1e293b", fg="#f8fafc",
            font=("Arial", 10), wrap="word", relief="flat",
            insertbackground="#f8fafc", padx=6, pady=4,
        )
        self._chat_input.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(8, 4))
        self._chat_input.bind("<Return>", self._on_chat_enter)

        self._chat_send_btn = tk.Button(
            input_bar, text="Send", command=self._send_chat_message,
            bg="#2563eb", fg="#ffffff", relief="flat",
            font=("Arial", 10, "bold"), padx=14, pady=4, cursor="hand2",
        )
        self._chat_send_btn.pack(side=tk.RIGHT, padx=(0, 8))

        # Chat display — packed after input so it fills remaining space
        display_wrap = tk.Frame(parent, bg="#1e293b")
        display_wrap.pack(side=tk.TOP, expand=True, fill=tk.BOTH)

        self._chat_display = tk.Text(
            display_wrap, bg="#1e293b", fg="#e2e8f0", font=("Arial", 10),
            wrap="word", state="disabled", relief="flat", padx=10, pady=6,
            cursor="arrow", selectbackground="#334155",
        )
        chat_vsb = tk.Scrollbar(display_wrap, command=self._chat_display.yview)
        self._chat_display.configure(yscrollcommand=chat_vsb.set)
        chat_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._chat_display.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        self._chat_display.tag_config("user_label",      foreground="#60a5fa", font=("Arial", 9, "bold"))
        self._chat_display.tag_config("user_text",       foreground="#bfdbfe", font=("Arial", 10))
        self._chat_display.tag_config("ai_label",        foreground="#34d399", font=("Arial", 9, "bold"))
        self._chat_display.tag_config("ai_text",         foreground="#e2e8f0", font=("Arial", 10))
        self._chat_display.tag_config("ai_thinking",     foreground="#64748b", font=("Arial", 10, "italic"))
        self._chat_display.tag_config("ai_h1",           foreground="#93c5fd", font=("Arial", 13, "bold"))
        self._chat_display.tag_config("ai_h2",           foreground="#7dd3fc", font=("Arial", 12, "bold"))
        self._chat_display.tag_config("ai_h3",           foreground="#67e8f9", font=("Arial", 11, "bold"))
        self._chat_display.tag_config("ai_bold",         foreground="#f1f5f9", font=("Arial", 10, "bold"))
        self._chat_display.tag_config("ai_italic",       foreground="#e2e8f0", font=("Arial", 10, "italic"))
        self._chat_display.tag_config("ai_inline_code",  foreground="#86efac", font=("Consolas", 9),
                                      background="#0f172a")
        self._chat_display.tag_config("ai_code_block",   foreground="#86efac", font=("Consolas", 9),
                                      background="#0f172a", lmargin1=16, lmargin2=16)
        self._chat_display.tag_config("ai_bullet_marker", foreground="#34d399", font=("Arial", 10, "bold"))
        self._chat_display.tag_config("ai_hr",            foreground="#334155", font=("Arial", 8))
        self._chat_display.tag_config("ai_table_header",  foreground="#93c5fd", font=("Consolas", 9, "bold"),
                                      background="#0f172a", lmargin1=8, lmargin2=8)
        self._chat_display.tag_config("ai_table_div",     foreground="#334155", font=("Consolas", 9),
                                      background="#0f172a", lmargin1=8, lmargin2=8)
        self._chat_display.tag_config("ai_table_cell",    foreground="#e2e8f0", font=("Consolas", 9),
                                      background="#0f172a", lmargin1=8, lmargin2=8)
        self._chat_display.tag_config("sys_text",         foreground="#64748b", font=("Arial", 9, "italic"))

        self._append_chat("sys", "Claude AI assistant — select a context tab above and start chatting.")

    def _refresh_chat_tabs(self):
        mode = self._chat_mode.get()
        for m, btn in self._chat_tab_btns.items():
            if m == mode:
                btn.config(bg="#1e293b", fg="#f8fafc")
            else:
                btn.config(bg="#0f172a", fg="#475569")

    def _set_chat_mode(self, mode):
        self._chat_mode.set(mode)
        self._refresh_chat_tabs()

    def _get_chat_context(self):
        """Build context string for the current tab mode."""
        if self._chat_mode.get() == "process":
            parts = [f"Current BPMN process:\n{json.dumps(self.model.to_json(), indent=2)}"]
            for link in self.model.links:
                fpath = link.get("file")
                if fpath and os.path.exists(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            parts.append(
                                f"Linked process ({os.path.basename(fpath)}):\n"
                                f"{json.dumps(json.load(f), indent=2)}"
                            )
                    except Exception:
                        pass
            return "\n\n".join(parts)
        else:
            if not self._repo_folder or not os.path.isdir(self._repo_folder):
                return "(No repository folder selected — click 'Set Folder…' to choose one.)"
            parts = []
            for fname in sorted(os.listdir(self._repo_folder)):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(self._repo_folder, fname), "r", encoding="utf-8") as f:
                            parts.append(f"Process: {fname}\n{json.dumps(json.load(f), indent=2)}")
                    except Exception:
                        pass
            return "\n\n---\n\n".join(parts) if parts else "(No JSON files found in repository folder.)"

    def _on_chat_enter(self, event):
        if event.state & 0x0001:   # Shift+Enter → newline
            return
        self._send_chat_message()
        return "break"

    def _send_chat_message(self):
        if not ANTHROPIC_AVAILABLE:
            self._append_chat("sys", "Error: 'anthropic' package not installed. Run: pip install anthropic")
            return
        if not self._claude_api_key:
            self._append_chat("sys", "No API key set — click 'API Key…' to configure.")
            return
        if self._chat_streaming:
            return
        msg = self._chat_input.get("1.0", "end-1c").strip()
        if not msg:
            return
        self._chat_input.delete("1.0", "end")
        self._append_chat("user", msg)
        self._chat_history.append({"role": "user", "content": msg})
        self._chat_streaming = True
        self._chat_send_btn.config(state="disabled", text="…")
        import threading
        threading.Thread(target=self._claude_stream_request, daemon=True).start()

    def _claude_stream_request(self):
        """Run in background thread: wait for the full Claude response then render it."""
        try:
            context = self._get_chat_context()
            system_prompt = (
                "You are a BPMN process analyst assistant. Help the user understand, analyse, "
                "and improve their business process models. The user's process data (JSON) follows.\n\n"
                + context
            )
            client = anthropic.Anthropic(api_key=self._claude_api_key)
            self.after(0, self._begin_ai_response)
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=system_prompt,
                messages=self._chat_history,
            ) as stream:
                message = stream.get_final_message()
            full_reply = message.content[0].text
            self._chat_history.append({"role": "assistant", "content": full_reply})
            self.after(0, self._display_ai_response, full_reply)
        except Exception as e:
            self.after(0, self._append_chat, "sys", f"Error: {e}")
            self.after(0, self._end_ai_response)

    def _begin_ai_response(self):
        d = self._chat_display
        d.config(state="normal")
        d.insert("end", "Claude: ", "ai_label")
        d.mark_set("ai_response_start", "end")
        d.mark_gravity("ai_response_start", "left")
        d.insert("end", "Thinking…\n\n", "ai_thinking")
        d.config(state="disabled")
        d.see("end")

    def _display_ai_response(self, text):
        d = self._chat_display
        d.config(state="normal")
        d.delete("ai_response_start", "end")
        self._render_markdown(text)
        d.insert("end", "\n", "ai_text")
        d.config(state="disabled")
        d.see("end")
        self._chat_streaming = False
        self._chat_send_btn.config(state="normal", text="Send")

    def _end_ai_response(self):
        """Called only on error to reset the send button."""
        self._chat_streaming = False
        self._chat_send_btn.config(state="normal", text="Send")

    def _render_markdown(self, text):
        """Parse markdown with mistune and render the AST into _chat_display."""
        import mistune
        md = mistune.create_markdown(renderer="ast", plugins=["table", "strikethrough", "url"])
        tokens = md(text)
        _TkMarkdownRenderer(self._chat_display).render(tokens)

    def _append_chat(self, role, text):
        self._chat_display.config(state="normal")
        if role == "user":
            self._chat_display.insert("end", "You: ", "user_label")
            self._chat_display.insert("end", text + "\n\n", "user_text")
        else:
            self._chat_display.insert("end", text + "\n\n", "sys_text")
        self._chat_display.config(state="disabled")
        self._chat_display.see("end")

    def _set_api_key(self):
        key = simpledialog.askstring(
            "Claude API Key", "Enter your Anthropic API key:",
            initialvalue=self._claude_api_key, parent=self,
        )
        if key is not None:
            self._claude_api_key = key.strip()
            self._save_recent_files()

    def _pick_repo_folder(self):
        folder = filedialog.askdirectory(
            title="Select Process Repository Folder",
            initialdir=self._repo_folder or os.path.expanduser("~"),
            parent=self,
        )
        if folder:
            self._repo_folder = folder
            self._save_recent_files()
            self._append_chat("sys", f"Repository folder: {folder}")

    def _clear_chat(self):
        self._chat_history.clear()
        self._chat_display.config(state="normal")
        self._chat_display.delete("1.0", "end")
        self._chat_display.config(state="disabled")
        self._append_chat("sys", "Chat cleared.")

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

            # Annotation field
            tk.Label(self.prop_content, text="Annotation", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(10, 1))
            annot_text = tk.Text(self.prop_content, height=6, bg="#334155", fg="#f8fafc",
                                 insertbackground="#f8fafc", relief="flat",
                                 font=("Arial", 9), wrap="word")
            annot_text.pack(fill="x", pady=(0, 6))
            if node.annotation:
                annot_text.insert("1.0", node.annotation)

            def on_annot_change(*_, nid=obj_id, widget=annot_text):
                n = self.model.nodes.get(nid)
                if n:
                    val = widget.get("1.0", "end-1c")
                    n.annotation = val if val.strip() else None

            annot_text.bind("<KeyRelease>", on_annot_change)
            
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

            # Annotation field
            tk.Label(self.prop_content, text="Annotation", bg="#1e293b", fg="#94a3b8",
                     font=("Arial", 9), anchor="w").pack(fill="x", pady=(10, 1))
            annot_text = tk.Text(self.prop_content, height=4, bg="#334155", fg="#f8fafc",
                                 insertbackground="#f8fafc", relief="flat",
                                 font=("Arial", 9), wrap="word")
            annot_text.pack(fill="x", pady=(0, 6))
            if edge.annotation:
                annot_text.insert("1.0", edge.annotation)

            def on_edge_annot_change(*_, eid=obj_id, widget=annot_text):
                e2 = next((ex for ex in self.model.edges if ex.id == eid), None)
                if e2:
                    val = widget.get("1.0", "end-1c")
                    e2.annotation = val if val.strip() else None

            annot_text.bind("<KeyRelease>", on_edge_annot_change)
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
            for tag in ('grid', 'pool', 'lane', 'edge', 'node', 'pool_handle', 'lane_handle', 'sel_indicator'):
                self.canvas.tag_lower(tag)
            self.canvas.tag_raise('grid')
            self.canvas.tag_raise('pool')
            self.canvas.tag_raise('lane')
            self.canvas.tag_raise('edge')
            self.canvas.tag_raise('node')
            self.canvas.tag_raise('pool_handle')
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

    def _nodes_in_pool(self, pool):
        """Return all lanes and non-pool nodes whose bounding box is inside the given pool."""
        result = []
        for n in self.model.nodes.values():
            if n is pool or n.type in ("pool", "externalPool"):
                continue
            if (pool.x <= n.x and pool.y <= n.y and
                    (n.x + n.w) <= (pool.x + pool.w) and
                    (n.y + n.h) <= (pool.y + pool.h)):
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
            if n.type in ("pool", "externalPool"):
                self.draw_pool(n)
        for n in self.model.nodes.values():
            if n.type == "lane":
                self.draw_lane(n)
        for e in self.model.edges:
            self.draw_edge(e)
        for n in self.model.nodes.values():
            if n.type not in ("lane", "pool", "externalPool"):
                self.draw_node(n)
        if self._active_lane_id and self._active_lane_id in self.model.nodes:
            self._draw_lane_handles(self.model.nodes[self._active_lane_id])
        self._update_scrollregion()
        self._stack_layers()
        self._draw_selection_overlays()
        self._update_search_highlights()
        self._refresh_minimap()

    # -------- Drawing
    def draw_pool(self, pool_node):
        is_ext = pool_node.type == "externalPool"
        dash_opts = {"dash": (6, 4)} if is_ext else {}
        x = self._mc(pool_node.x)
        y = self._mc(pool_node.y)
        w = self._mc(pool_node.w)
        h = self._mc(pool_node.h)
        font_size = max(6, int(12 * self._zoom))
        rect = self.canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=pool_node.fill, outline=pool_node.outline, width=2,
            tags=("pool", f"pool:{pool_node.id}"), **dash_opts,
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

        elif node.type == "annotation":
            x2, y2 = self._mc(node.x), self._mc(node.y)
            w2, h2 = self._mc(node.w), self._mc(node.h)
            rect = self.canvas.create_rectangle(
                x2, y2, x2 + w2, y2 + h2,
                fill=node.fill, outline=node.fill, width=0, tags=tag,
            )
            border = self.canvas.create_line(
                x2, y2, x2, y2 + h2,
                fill=node.outline, width=3, tags=tag,
            )
            fs = max(6, int(10 * self._zoom))
            label = self.canvas.create_text(
                x2 + self._mc(8), y2 + h2 / 2,
                text=node.text, anchor="w",
                font=("Arial", fs), fill=node.text_color, tags=tag,
            )
            self._node_by_item[rect] = node.id
            self._node_by_item[border] = node.id
            self._label_by_item[label] = (node.id, "node_label")

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

    # -------- Pool handles (resize)
    def _clear_pool_handles(self):
        for item in list(self._pool_handle_to_info.keys()):
            self.canvas.delete(item)
        self._pool_handle_to_info.clear()

    def _draw_pool_handles(self, pool_node):
        self._clear_pool_handles()
        x = self._mc(pool_node.x)
        y = self._mc(pool_node.y)
        w = self._mc(pool_node.w)
        h = self._mc(pool_node.h)
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
                fill="#2563eb", outline="#1e3a8a", tags=("pool_handle",),
            )
            self._pool_handle_to_info[r] = (pool_node.id, anchor)
        self._stack_layers()

    def _update_pool_graphics(self, pool_node):
        x = self._mc(pool_node.x)
        y = self._mc(pool_node.y)
        w = self._mc(pool_node.w)
        h = self._mc(pool_node.h)
        items = self.canvas.find_withtag(f"pool:{pool_node.id}")
        for it in items:
            t = self.canvas.type(it)
            if t == 'rectangle':
                self.canvas.coords(it, x, y, x + w, y + h)
            elif t == 'text':
                self.canvas.coords(it, x + self._mc(8), y + self._mc(16))
        if self._active_pool_id == pool_node.id:
            self._draw_pool_handles(pool_node)

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
        if item_id in self._pool_handle_to_info:
            return "pool_handle"
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

    def _is_chat_widget(self, event):
        """Return True if the scroll event originated from the chat display or input."""
        w = event.widget
        return w is getattr(self, "_chat_display", None) or w is getattr(self, "_chat_input", None)

    def _on_mouse_wheel(self, event):
        if self._is_chat_widget(event):
            return  # let the Text widget scroll itself
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
        self._refresh_minimap()

    def _on_mouse_wheel_linux_up(self, event):
        if self._is_chat_widget(event):
            return
        if event.state & 0x0004:
            self.zoom_in()
        elif event.state & 0x0001:
            self.canvas.xview_scroll(-1, "units")
        else:
            self.canvas.yview_scroll(-1, "units")
        self._refresh_minimap()

    def _on_mouse_wheel_linux_down(self, event):
        if self._is_chat_widget(event):
            return
        if event.state & 0x0004:
            self.zoom_out()
        elif event.state & 0x0001:
            self.canvas.xview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(1, "units")
        self._refresh_minimap()

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

        # Pool handle resize begin
        if clicked_kind == "pool_handle":
            pool_id, anchor = self._pool_handle_to_info.get(item, (None, None))
            if pool_id and pool_id in self.model.nodes:
                pn = self.model.nodes[pool_id]
                self._resizing_pool = {
                    "pool_id": pool_id,
                    "anchor": anchor,
                    "start_mouse": (cx, cy),
                    "start_geom": (pn.x, pn.y, pn.w, pn.h),
                }
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
                self._active_lane_id = None
                self._clear_lane_handles()
                self._active_pool_id = None
                self._clear_pool_handles()
                self._selected_item = None
                self._selected_type = None
                self._multi_select.clear()
                self._draw_selection_overlays()
                ctrl_held = bool(event.state & 0x0004)
                if ctrl_held:
                    # Ctrl+drag → start rubber-band selection
                    mx, my = self._cm(cx), self._cm(cy)
                    self._rubber_band_start = (mx, my)
                    self._rubber_band_item = self.canvas.create_rectangle(
                        cx, cy, cx, cy,
                        outline="#2563eb", width=1, dash=(4, 3), tags=("sel_indicator",)
                    )
                else:
                    # Plain drag → pan canvas
                    self.canvas.scan_mark(event.x, event.y)
                    self._panning = True
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
                    self._active_pool_id = None
                    self._clear_pool_handles()
                    self._draw_lane_handles(ln)
                    self._stack_layers()
                    self._multi_select.clear()
                    self._draw_selection_overlays()
                    self._update_properties_panel(nid, "lane")
                return

            # Pool drag — move the pool and all contained lanes/nodes
            if clicked_kind == "pool":
                nid = self._resolve_node_id_from_item(item)
                if nid and nid in self.model.nodes:
                    pn = self.model.nodes[nid]
                    self._dragging_pool = {'pool_id': nid, 'offset': (mx - pn.x, my - pn.y)}
                    self._selected_item = item
                    self._selected_type = 'pool'
                    self._active_lane_id = None
                    self._clear_lane_handles()
                    self._active_pool_id = nid
                    self._draw_pool_handles(pn)
                    self._multi_select.clear()
                    self._draw_selection_overlays()
                    self._update_properties_panel(nid, "pool")
                return

            # Node / edge
            self._active_lane_id = None
            self._clear_lane_handles()
            self._active_pool_id = None
            self._clear_pool_handles()
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
                      "lane", "pool", "annotation", "externalPool")
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
        if getattr(self, '_panning', False):
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        cx, cy = self._event_xy_canvas(event)
        mx, my = self._cm(cx), self._cm(cy)

        # Rubber-band selection
        if self._rubber_band_start is not None:
            rbx, rby = self._rubber_band_start
            # _rubber_band_start stores model coords; convert to canvas
            rbcx, rbcy = self._mc(rbx), self._mc(rby)
            if self._rubber_band_item:
                self.canvas.delete(self._rubber_band_item)
            self._rubber_band_item = self.canvas.create_rectangle(
                rbcx, rbcy, cx, cy,
                outline="#2563eb", width=1, dash=(4, 3), fill="",
                tags=("sel_indicator",),
            )
            return

        # Pool resizing
        if self._resizing_pool:
            pool_id = self._resizing_pool["pool_id"]
            if pool_id not in self.model.nodes:
                return
            anchor = self._resizing_pool["anchor"]
            scx, scy = self._resizing_pool["start_mouse"]
            px, py, pw, ph = self._resizing_pool["start_geom"]
            dcx, dcy = cx - scx, cy - scy
            dx, dy = self._cm(dcx), self._cm(dcy)
            nx, ny, nw, nh = px, py, pw, ph
            minw, minh = 200, 80
            if anchor in ("nw", "w", "sw"):
                nx = px + dx
                nw = pw - dx
            if anchor in ("ne", "e", "se"):
                nw = pw + dx
            if anchor in ("nw", "n", "ne"):
                ny = py + dy
                nh = ph - dy
            if anchor in ("sw", "s", "se"):
                nh = ph + dy
            if nw < minw:
                if anchor in ("nw", "w", "sw"):
                    nx = px + (pw - minw)
                nw = minw
            if nh < minh:
                if anchor in ("nw", "n", "ne"):
                    ny = py + (ph - minh)
                nh = minh
            pool = self.model.nodes[pool_id]
            pool.x, pool.y, pool.w, pool.h = nx, ny, nw, nh
            self._update_pool_graphics(pool)
            self._draw_selection_overlays()
            self._changed_during_drag = True
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
            self._draw_selection_overlays()
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
                    self._draw_selection_overlays()
                    self._changed_during_drag = True
            return

        # Pool dragging — move the pool and all contained lanes/nodes
        if self._dragging_pool:
            pool_id = self._dragging_pool.get('pool_id')
            if pool_id and pool_id in self.model.nodes:
                pn = self.model.nodes[pool_id]
                offx, offy = self._dragging_pool.get('offset', (0, 0))
                nx, ny = self.snap(mx - offx, my - offy)
                dx, dy = nx - pn.x, ny - pn.y
                if dx or dy:
                    children = self._nodes_in_pool(pn)
                    pn.x, pn.y = nx, ny
                    self.canvas.move(f"pool:{pool_id}", dx * self._zoom, dy * self._zoom)
                    for n in children:
                        n.x += dx
                        n.y += dy
                        tag = f"lane:{n.id}" if n.type == "lane" else f"node:{n.id}"
                        self.canvas.move(tag, dx * self._zoom, dy * self._zoom)
                    self.canvas.delete("edge")
                    self._edge_by_item.clear()
                    for e in self.model.edges:
                        self.draw_edge(e)
                    self._update_scrollregion()
                    if self._active_pool_id == pool_id:
                        self._draw_pool_handles(pn)
                    self._stack_layers()
                    self._draw_selection_overlays()
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
        if getattr(self, '_panning', False):
            self._panning = False
            return

        # Finish rubber-band selection
        if self._rubber_band_start is not None:
            cx, cy = self._event_xy_canvas(event)
            rbx, rby = self._rubber_band_start
            # _rubber_band_start stores model coords
            x1m = min(rbx, self._cm(cx))
            y1m = min(rby, self._cm(cy))
            x2m = max(rbx, self._cm(cx))
            y2m = max(rby, self._cm(cy))
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

        if self._resizing_pool:
            self._resizing_pool = None
            self._stack_layers()
            self._update_scrollregion()
            if self._active_pool_id and self._active_pool_id in self.model.nodes:
                self._draw_pool_handles(self.model.nodes[self._active_pool_id])
            if self._changed_during_drag:
                self._push_history("resize pool")
                self._changed_during_drag = False
        elif self._resizing_lane:
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
        elif self._dragging_pool:
            self._dragging_pool = None
            self._stack_layers()
            self._update_scrollregion()
            if self._changed_during_drag:
                self._push_history("move pool")
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
        self._update_process_tabs()
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
            self._add_recent_file(path)
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
        self._do_open_json(path)

    def _do_open_json(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.model.load_json(data)
            self._load_external_links()
            self.current_file = path
            self._active_lane_id = None
            self._clear_lane_handles()
            self._dirty = False
            self._multi_select.clear()
            if self.view_mode == "bpmn":
                self.redraw_all()
            else:
                self.toggle_view_json()
            self._update_process_tabs()
            self._add_recent_file(path)
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
                ("textAnnotation", "annotation"),
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
            elif node.type == "annotation":
                el = E("textAnnotation", id=node.id)
                txt = ET.SubElement(el, self.q("text"))
                txt.text = node.text or ""
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
