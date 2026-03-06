# bpmn_to_json

A lightweight desktop app for drawing BPMN-style diagrams, editing them in JSON, and importing/exporting BPMN XML/JSON. Built with Tkinter.

## Features
- **Graphical editor** with grid & panning, undo/redo, and a left toolbar for nodes: Start/End events, Task, Exclusive Gateway, Swimlane, Pool.  
- **Connectors**: Sequence Flow (solid arrow), Message Flow (dashed arrow).  
- **JSON view**: Toggle between canvas and raw JSON representation; load/save JSON.  
- **BPMN XML import/export** (basic subset).  
- **PNG export** via Canvas PostScript → Pillow conversion (optional; requires Pillow and Ghostscript).  

## Requirements
- **Python 3.8+** (tested with modern CPython).  
- **Tk / Tkinter** available on your system.
  - Windows/macOS: usually included with the official Python installer.
  - Linux: install your distro’s Tk package, e.g. `sudo apt-get install python3-tk` (Debian/Ubuntu), `sudo dnf install python3-tkinter` (Fedora), or `sudo pacman -S tk` (Arch).
- **Pillow** (only for PNG export). Installed from `requirements.txt`.
- **Ghostscript** (only for PNG export from PostScript): `brew install ghostscript` (macOS), `sudo apt-get install ghostscript` (Debian/Ubuntu), or install from the official site on Windows and ensure `gs` is on `PATH`.

## Set up & run (using a Python virtual environment)

### 1) Create and activate a venv
**macOS / Linux (bash/zsh):**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```
> If you don’t need PNG export, you may skip installing Pillow by removing it from `requirements.txt` first.

### 3) Run the app
```bash
python bpmn_studio.py
```

## How to use
- **Add elements**: Choose a tool on the left (e.g., Task, Start Event) and click on the canvas to place.
- **Select/Move**: Choose *Select/Move*, then drag elements. Nodes snap to the grid.
- **Connect**: Choose *Sequence Flow* or *Message Flow*, click source node then target node.
- **Rename**: Double-click a node, lane/pool label, or edge label to edit text.
- **Delete**: Select an item and press `Delete`, or right‑click → *Delete*.
- **Bring forward / Send backward**: Right‑click selected item.
- **Lanes (Swimlanes)**: Click a lane to reveal resize handles; drag handles to resize or drag lane to move. Active lane shows blue handles.
- **View**: *View → JSON View* to inspect/edit JSON; *View → BPMN View* to return to canvas. When switching back, the app will parse your JSON into the diagram.
- **Files**:
  - *File → Open JSON…* / *Save* / *Save As…*
  - *File → Open BPMN XML…* (import from `.bpmn`/`.xml`)
  - *File → Export BPMN XML…*
  - *File → Export PNG…* (requires Pillow and Ghostscript)

## Notes on export to PNG
- The app saves the canvas to **PostScript** and (if Pillow is installed) converts it to **PNG**. Pillow’s PostScript/EPS support uses **Ghostscript** under the hood, so make sure `gs` is installed and on your `PATH`.
- If Pillow is **not** available, the app will save a `.ps` file instead, which you can convert externally.

## Troubleshooting
- **`_tkinter.TclError: no display name and no $DISPLAY environment variable`**: You’re on a headless system (e.g., WSL/SSH). Run on a desktop environment or enable X forwarding with a proper X server.
- **`ModuleNotFoundError: No module named 'PIL'`**: Install requirements: `pip install -r requirements.txt`. PNG export is optional; you can skip Pillow if you don’t need it.
- **PNG export doesn’t work / `gs` not found**: Install Ghostscript and ensure the `gs` executable is in your `PATH`, or export to PostScript and convert manually.

## Project structure
```
.
├── bpmn_studio.py        # Main Tkinter application
├── requirements.txt      # Python dependencies (only Pillow is non‑stdlib)
└── README.md             # This file
```
