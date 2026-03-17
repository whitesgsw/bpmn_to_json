# BPMN Studio

A lightweight desktop application for drawing, editing, and analysing BPMN-style process diagrams. Built with Python and Tkinter — no web browser or heavy framework required.

> **Contributions welcome.** Submit a pull request to add features, or open an issue on the repo's Issue tab for bugs and feature requests.

---

## Features

### Canvas & Editing
- **9 node types**: Start Event, End Event, Task, Exclusive Gateway, Parallel Gateway, Inclusive Gateway, Intermediate Event, Swimlane, Pool
- **3 edge types**: Sequence Flow, Message Flow, Linked Process
- **Drag & drop** placement; nodes snap to the configurable grid
- **Select & move** single nodes or multi-select with Ctrl+Click / Ctrl+Drag rubber-band
- **Resize** lanes and pools with 8-point handles; minimum-size constraints enforced
- **Rename** any node, lane, pool, or edge label by double-clicking
- **Copy / Paste** (Ctrl+C / Ctrl+V) — preserves properties and internal edges between copied nodes
- **Undo / Redo** (Ctrl+Z / Ctrl+Y) — full snapshot stack (up to 100 entries)
- **Delete** selected element(s) with the Delete key or right-click menu
- **Auto Layout** — BFS-based hierarchical left-to-right layout
- **Validate** — checks for missing start/end events, dangling edges, isolated nodes, and under-connected gateways

### Navigation & View
- **Zoom** in/out (Ctrl+Scroll or toolbar buttons); reset to 100 %
- **Pan** with Space+drag, middle-mouse drag, or Shift+Scroll (horizontal)
- **Minimap** — toggleable overview panel; click to jump to a region
- **Search** (Ctrl+F) — find nodes by name with previous/next navigation
- **Grid** — visual guide with snap-to-grid toggle
- **BPMN View / JSON View** toggle (View menu) — switch between canvas and raw JSON editor

### Properties Panel
Contextual right-hand panel showing, for any selected element:
- Editable name and annotation fields
- Fill, outline, and text colour pickers
- Condition expression (edges)
- Read-only type and ID

### Right-Click Context Menu
Delete, Bring Forward, Send Backward, Change Fill/Outline/Text Colour, Remove Link

### File Operations
| Action | Format |
|--------|--------|
| Open / Save / Save As | JSON (`.json`) — native format |
| Import | BPMN XML (`.bpmn`, `.xml`) |
| Export | BPMN XML, PNG (requires Pillow + Ghostscript), PostScript (fallback) |
| Link External Process | Reference another BPMN file as an External Pool |

- **Recent Files** — up to 8 files persisted in `~/.bpmn_studio_config.json`; missing files are detected automatically
- **Multiple processes** — a single JSON file can contain multiple named processes

### Claude AI Assistant
An integrated chat panel (bottom pane, resizable) for interrogating and improving your diagrams:
- **Current Process tab** — sends the active diagram's JSON as context for analysis
- **Process Repository tab** — loads all JSON files from a chosen folder for cross-process queries
- Responses are rendered with full **Markdown formatting**: headings, bold/italic, inline and fenced code, tables, bullet and numbered lists
- Chat history is preserved for the session; "Clear" resets it
- Requires an [Anthropic API key](https://console.anthropic.com/) (set via the *API Key…* button)

---

## Keyboard Shortcuts

### Tool Selection (BPMN view; ignored when a text field is focused)
| Key | Tool |
|-----|------|
| `s` | Select / Move |
| `t` | Task |
| `b` | Start Event |
| `e` | End Event |
| `x` | Exclusive Gateway |
| `p` | Parallel Gateway |
| `i` | Inclusive Gateway |
| `m` | Intermediate Event |
| `l` | Swimlane |
| `o` | Pool |
| `c` | Sequence Flow |
| `f` | Message Flow |

### Global
| Shortcut | Action |
|----------|--------|
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |
| Ctrl+C | Copy selected |
| Ctrl+V | Paste |
| Ctrl+A | Select All |
| Ctrl+F | Find / Search |
| Delete | Delete selected |
| Double-click | Rename node / edge label |
| Space + drag | Pan canvas |
| Ctrl+Scroll | Zoom in / out |
| Shift+Scroll | Pan horizontally |Col

---

## Requirements

| Dependency | Purpose | Required? |
|------------|---------|-----------|
| Python 3.8+ | Runtime | Yes |
| Tkinter | GUI framework (bundled with most Python installs) | Yes |
| `anthropic` | Claude AI assistant | Yes (AI features) |
| `mistune >= 3.0` | Markdown rendering in chat panel | Yes (AI features) |
| `Pillow >= 10.0` | PNG export | Optional |
| Ghostscript (`gs`) | PNG conversion from PostScript | Optional (PNG export) |

**Tkinter on Linux** — install via your package manager if missing:
```bash
# Debian / Ubuntu
sudo apt-get install python3-tk
# Fedora
sudo dnf install python3-tkinter
# Arch
sudo pacman -S tk
```

**Ghostscript** — required only for PNG export:
```bash
brew install ghostscript          # macOS
sudo apt-get install ghostscript  # Debian / Ubuntu
# Windows: download from https://ghostscript.com and add gs to PATH
```

---

## Setup & Run

### 1. Create and activate a virtual environment

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

> If you don't need AI features or PNG export, you can remove the relevant packages from `requirements.txt` before installing.

### 3. Run
```bash
python bpmn_studio.py
```

---

## How to Use

### Building a diagram
1. Select a tool from the left toolbar (or press its keyboard shortcut).
2. Click on the canvas to place a node.
3. Switch to **Sequence Flow** (`c`) or **Message Flow** (`f`), then click a source node followed by a target node to connect them.
4. **Double-click** any element to rename it.
5. Use the **Properties Panel** on the right to set colours and add annotations.

### Swimlanes & Pools
- Place a **Pool** first, then add **Swimlanes** inside it.
- Click a lane to reveal its resize handles (blue); drag to resize or reposition.
- Nodes placed inside a lane are associated with it automatically.

### Search
Press **Ctrl+F** to open the search bar at the top of the canvas. Type to filter nodes by name; use **▲ / ▼** to cycle through matches. Press **✕** or Ctrl+F again to close.

### JSON View
*View → JSON View* opens a raw text editor showing the diagram's JSON representation. Edit directly and switch back to *BPMN View* to re-parse — the canvas will reflect your changes.

### AI Assistant
1. Click **API Key…** in the chat panel header and enter your Anthropic API key.
2. Select a context tab: **Current Process** or **Process Repository** (set a folder with **Set Folder…**).
3. Type a question and press **Enter** (Shift+Enter for a newline).

### PNG Export
*File → Export PNG…* renders the canvas to PostScript and converts it to PNG via Ghostscript. If Ghostscript is not installed, a `.ps` file is saved instead.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `_tkinter.TclError: no display name and no $DISPLAY environment variable` | You are on a headless system (WSL/SSH). Run on a desktop or enable X forwarding. |
| `ModuleNotFoundError: No module named 'PIL'` | Run `pip install -r requirements.txt`. PNG export is optional. |
| PNG export fails / `gs` not found | Install Ghostscript and ensure `gs` is on your `PATH`, or export to PostScript and convert manually. |
| `ModuleNotFoundError: No module named 'anthropic'` | Run `pip install anthropic`. Required for the AI assistant. |
| `ModuleNotFoundError: No module named 'mistune'` | Run `pip install mistune`. Required for AI chat markdown rendering. |

---

## Project Structure

```
.
├── bpmn_studio.py        # Main application (single-file)
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

Configuration is persisted to `~/.bpmn_studio_config.json` (recent files, API key, repository folder path).
