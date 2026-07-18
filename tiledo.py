#!/usr/bin/env python3
"""TileDo — tile-based task boards, recurring checklists and reference notes.

Design language follows factory-planner (github.com/p-scott-0/factory-planner):
charcoal surfaces, amber accent, quiet borders, uppercase micro-labels.
"""

import sys, os, re, json, uuid, base64, copy, subprocess, ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import urllib.request

try:
    import winreg
except ImportError:
    winreg = None

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QDialog, QLabel,
    QPushButton, QToolButton, QMenu, QLineEdit, QTextEdit,
    QScrollArea, QSizeGrip, QCheckBox, QSpinBox, QProgressBar,
    QColorDialog, QFileDialog, QStackedWidget, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QShortcut, QComboBox, QRadioButton, QButtonGroup,
    QVBoxLayout, QHBoxLayout, QSizePolicy, QMessageBox, QSystemTrayIcon,
)
from PyQt5.QtCore import (
    Qt, QPoint, QTimer, QThread, QMimeData, QEvent,
    pyqtSignal, QBuffer, QIODevice, QRect, QAbstractNativeEventFilter,
)
from PyQt5.QtGui import (
    QColor, QPalette, QDrag, QTextCursor, QTextCharFormat, QFont,
    QTextListFormat, QKeySequence, QImage, QPixmap, QPainter, QIcon,
    QTextTableFormat, QTextLength,
)
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

APP_VERSION = "2.1.0"
GITHUB_REPO = "p-scott-0/tiledo"

# ══════════════════════════════════════════════════════════════════════════════
# Design tokens — factory-planner palette
# ══════════════════════════════════════════════════════════════════════════════
BG     = "#16181a"   # window background
NAV    = "#111315"   # titlebar / nav strip
SURF   = "#1f2225"   # card surface
SURF2  = "#191c1e"   # inset surface (chips, inputs)
SURF_H = "#24282c"   # card hover
BDR    = "#2e3236"   # border
BDR_H  = "#3a3f44"   # border hover / strong
TEXT   = "#d0d4d8"
DIM    = "#7a8088"
FAINT  = "#4a5058"
ACC    = "#e8982a"   # amber accent
ACC_H  = "#f5a83a"
GRN    = "#4caa5c"   # done / progress
RED    = "#cc4444"

PRIO_ORDER = {"high": 0, "medium": 1, "low": 2}
PRIO_LABEL = {"high": "High", "medium": "Normal", "low": "Low"}
DEFAULT_PRIO_COLOR = {"high": "#cc4444", "medium": "#e8982a", "low": "#4a90d0"}
PRIO_COLOR = dict(DEFAULT_PRIO_COLOR)

DEFAULT_STAGES = [
    {"id": "todo",        "name": "To Do",       "color": "#7a8088"},
    {"id": "in_progress", "name": "In Progress", "color": "#4a90d0"},
    {"id": "blocked",     "name": "Blocked",     "color": "#cc4444"},
    {"id": "review",      "name": "Review",      "color": "#e8982a"},
]
DEFAULT_CFG = {
    "tile_size": 230, "x": 100, "y": 60, "w": 1000, "h": 720,
    "auto_update": True, "ui_version": 2,
    "close_to_tray": True, "hotkey_enabled": True,
    "priority_color": dict(DEFAULT_PRIO_COLOR),
}

# ══════════════════════════════════════════════════════════════════════════════
# Data layer — atomic writes, backup recovery, migrations
# ══════════════════════════════════════════════════════════════════════════════
DATA_DIR   = Path(os.environ.get("TILEDO_DATA_DIR", str(Path.home() / ".tiledo")))
DATA_FILE  = DATA_DIR / "data.json"
NOTES_FILE = DATA_DIR / "notes.json"
CFG_FILE   = DATA_DIR / "settings.json"

def _atomic_write(path: Path, payload: dict):
    """tmp-write + rename so a crash can never leave a half-written file.
    The previous good file is kept as .bak."""
    DATA_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    if path.exists():
        try:
            os.replace(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass
    os.replace(tmp, path)

def _read_json(path: Path):
    """Read a JSON file, falling back to its .bak if the main file is corrupt."""
    for p in (path, path.with_suffix(path.suffix + ".bak")):
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None

def mk_task(title, priority="medium", parent_id=None, recurring=False):
    return {"id": str(uuid.uuid4()), "title": title, "notes": "",
            "priority": priority, "stage": "todo", "parent_id": parent_id,
            "recurring": recurring, "completed": False, "order": 999999,
            "created": datetime.now().isoformat()}

def load_data():
    d = _read_json(DATA_FILE) or {}
    d.setdefault("tasks", [])
    d.setdefault("templates", [])
    if not d.get("stages"):
        d["stages"] = [dict(s) for s in DEFAULT_STAGES]

    # migrate v1 notes out of data.json into notes.json
    if "notes_tabs" in d:
        if not NOTES_FILE.exists():
            _atomic_write(NOTES_FILE, {"tabs": d["notes_tabs"]})
        del d["notes_tabs"]
    d.pop("notes_html", None)

    # normalise task fields + repair orphans (parent deleted in v1 left zombies)
    ids = {t.get("id") for t in d["tasks"]}
    for t in d["tasks"]:
        t.setdefault("id", str(uuid.uuid4()))
        t.setdefault("title", "(untitled)")
        t.setdefault("notes", "")
        t.setdefault("stage", "todo")
        t.setdefault("recurring", False)
        t.setdefault("completed", False)
        t.setdefault("order", 999999)
        if t.get("priority") not in PRIO_ORDER:
            t["priority"] = "medium"
        if t.get("parent_id") and t["parent_id"] not in ids:
            t["parent_id"] = None          # orphan → surface at root so it isn't lost
        elif "parent_id" not in t:
            t["parent_id"] = None
    return d

def save_data(d):
    _atomic_write(DATA_FILE, d)

def load_notes():
    n = _read_json(NOTES_FILE) or {}
    tabs = n.get("tabs") or []
    if not tabs:
        tabs = [{"id": str(uuid.uuid4()), "name": "Notes", "html": ""}]
    return {"tabs": tabs}

def save_notes(n):
    _atomic_write(NOTES_FILE, n)

def load_cfg():
    cfg = _read_json(CFG_FILE) or {}
    cfg = {**DEFAULT_CFG, **cfg}
    # v1 → v2 palette migration: old saved colours would fight the new theme
    if cfg.get("ui_version") != 2:
        cfg["priority_color"] = dict(DEFAULT_PRIO_COLOR)
        cfg["ui_version"] = 2
    cfg.pop("priority_bg", None); cfg.pop("priority_acc", None)
    pc = cfg.get("priority_color") or {}
    for k in PRIO_ORDER:
        PRIO_COLOR[k] = pc.get(k, DEFAULT_PRIO_COLOR[k])
    return cfg

def save_cfg(c):
    c["priority_color"] = dict(PRIO_COLOR)
    c["ui_version"] = 2
    _atomic_write(CFG_FILE, c)

# ── task tree helpers ─────────────────────────────────────────────────────────
def task_by_id(d, tid):
    for t in d["tasks"]:
        if t["id"] == tid:
            return t
    return None

def children_of(d, pid, include_done=True):
    kids = [t for t in d["tasks"]
            if t.get("parent_id") == pid and not t.get("recurring")]
    if not include_done:
        kids = [t for t in kids if not t.get("completed")]
    kids.sort(key=lambda t: (PRIO_ORDER.get(t["priority"], 1), t.get("order", 0)))
    return kids

def descendant_ids(d, tid):
    out, stack = set(), [tid]
    kids_map = {}
    for t in d["tasks"]:
        kids_map.setdefault(t.get("parent_id"), []).append(t["id"])
    while stack:
        cur = stack.pop()
        for k in kids_map.get(cur, []):
            if k not in out:
                out.add(k); stack.append(k)
    return out

def ancestor_chain(d, tid):
    """[root-most … immediate parent] of task tid."""
    chain, seen = [], set()
    t = task_by_id(d, tid)
    while t and t.get("parent_id") and t["parent_id"] not in seen:
        seen.add(t["parent_id"])
        p = task_by_id(d, t["parent_id"])
        if not p: break
        chain.append(p); t = p
    return list(reversed(chain))

def cascade_complete(d, tid, val):
    t = task_by_id(d, tid)
    if t: t["completed"] = val
    if val:
        for did in descendant_ids(d, tid):
            dt = task_by_id(d, did)
            if dt: dt["completed"] = True

def cascade_delete(d, tid):
    doomed = descendant_ids(d, tid) | {tid}
    d["tasks"] = [t for t in d["tasks"] if t["id"] not in doomed]

def bucket(d, parent_id, priority, recurring=False):
    """Pending siblings sharing parent + priority — the reorder unit."""
    ts = [t for t in d["tasks"]
          if bool(t.get("recurring")) == recurring
          and not t.get("completed")
          and t.get("parent_id") == parent_id
          and (recurring or t.get("priority") == priority)]
    ts.sort(key=lambda t: t.get("order", 0))
    return ts

def renumber(ts):
    for i, t in enumerate(ts):
        t["order"] = i * 10

def insert_relative(d, src, target, where):
    """Reorder src before/after target, adopting target's parent + priority."""
    rec = bool(src.get("recurring"))
    src["parent_id"] = target.get("parent_id")
    if not rec:
        src["priority"] = target["priority"]
    b = [t for t in bucket(d, target.get("parent_id"), target.get("priority"), rec)
         if t["id"] != src["id"]]
    idx = next((i for i, t in enumerate(b) if t["id"] == target["id"]), len(b))
    if where == "after":
        idx += 1
    b.insert(idx, src)
    renumber(b)

def nest_under(d, src, new_parent):
    src["parent_id"] = new_parent["id"]
    b = bucket(d, new_parent["id"], src["priority"])
    if src not in b:
        b.append(src)
    renumber(b)

def top_pending_count(d):
    return sum(1 for t in d["tasks"]
               if not t.get("completed") and not t.get("recurring")
               and t.get("parent_id") is None)

def stage_by_id(d, sid):
    for s in d.get("stages", []):
        if s["id"] == sid:
            return s
    return {"id": sid, "name": "—", "color": FAINT}

# ── archive ───────────────────────────────────────────────────────────────────
ARCHIVE_FILE = DATA_DIR / "archive.json"

def load_archive():
    a = _read_json(ARCHIVE_FILE) or {}
    a.setdefault("tasks", [])
    return a

def save_archive(a):
    _atomic_write(ARCHIVE_FILE, a)

def archive_task(d, tid):
    """Move a task and its whole subtree from the working set into archive.json."""
    root = task_by_id(d, tid)
    if not root:
        return
    ids = descendant_ids(d, tid) | {tid}
    moved = [t for t in d["tasks"] if t["id"] in ids]
    d["tasks"] = [t for t in d["tasks"] if t["id"] not in ids]
    root["parent_id"] = None
    root["archived_at"] = datetime.now().isoformat()
    a = load_archive()
    a["tasks"].extend(moved)
    save_archive(a)

def _archive_subtree_ids(a, root_id):
    kmap = {}
    for t in a["tasks"]:
        kmap.setdefault(t.get("parent_id"), []).append(t["id"])
    ids, stack = {root_id}, [root_id]
    while stack:
        for k in kmap.get(stack.pop(), []):
            if k not in ids:
                ids.add(k); stack.append(k)
    return ids

def restore_archived(d, root_id):
    a = load_archive()
    ids = _archive_subtree_ids(a, root_id)
    moved = [t for t in a["tasks"] if t["id"] in ids]
    a["tasks"] = [t for t in a["tasks"] if t["id"] not in ids]
    save_archive(a)
    root = next((t for t in moved if t["id"] == root_id), None)
    if root:
        root.pop("archived_at", None)
        b = bucket(d, None, root.get("priority", "medium"))
        root["order"] = max((x.get("order", 0) for x in b), default=-10) + 10
    d["tasks"].extend(moved)

def delete_archived(root_id):
    a = load_archive()
    ids = _archive_subtree_ids(a, root_id)
    a["tasks"] = [t for t in a["tasks"] if t["id"] not in ids]
    save_archive(a)

# ── templates ─────────────────────────────────────────────────────────────────
def template_items_from(d, tid):
    return [{"title": k["title"], "children": template_items_from(d, k["id"])}
            for k in children_of(d, tid)]

def instantiate_items(d, items, parent_id, priority="medium"):
    for i, it in enumerate(items):
        t = mk_task(it.get("title", "item"), priority, parent_id)
        t["order"] = i * 10
        d["tasks"].append(t)
        instantiate_items(d, it.get("children") or [], t["id"], priority)

def count_template_items(items):
    return sum(1 + count_template_items(it.get("children") or []) for it in items)

# ── waiting-on ────────────────────────────────────────────────────────────────
def waiting_days(t):
    w = t.get("waiting")
    if not w or not w.get("since"):
        return None
    try:
        return max(0, (datetime.now() - datetime.fromisoformat(w["since"])).days)
    except Exception:
        return None

# ── start-with-Windows (HKCU Run key) ─────────────────────────────────────────
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def _startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = pyw if pyw.exists() else py
    return f'"{exe}" "{Path(__file__).resolve()}" --tray'

def get_startup_enabled():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "TileDo")
        return True
    except OSError:
        return False

def set_startup(enabled):
    if not winreg:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, "TileDo", 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(k, "TileDo")
                except OSError:
                    pass
    except OSError:
        pass

def make_app_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACC))
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("#141414"))
    f = QFont("Segoe UI", 28, QFont.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "T")
    p.end()
    return QIcon(pm)

# ══════════════════════════════════════════════════════════════════════════════
# Stylesheet
# ══════════════════════════════════════════════════════════════════════════════
SS = f"""
QLabel {{ color: {TEXT}; background: transparent; }}
QToolTip {{ background: {NAV}; color: {TEXT}; border: 1px solid {BDR_H}; padding: 4px 8px; }}

QLineEdit, QTextEdit {{
    background: {BG}; border: 1px solid {BDR_H}; border-radius: 5px;
    padding: 6px 9px; color: {TEXT}; selection-background-color: {ACC};
    selection-color: #111;
}}
QLineEdit:focus, QTextEdit:focus {{ border-color: {ACC}; }}

QComboBox {{
    background: {BG}; border: 1px solid {BDR_H}; border-radius: 5px;
    padding: 5px 9px; color: {TEXT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {SURF}; border: 1px solid {BDR_H}; border-radius: 6px;
    selection-background-color: #272b2f; color: {TEXT}; padding: 3px; outline: 0;
}}

QPushButton {{
    background: #272b2f; color: {TEXT}; border: 1px solid {BDR_H};
    border-radius: 5px; padding: 6px 13px; font-weight: 600;
}}
QPushButton:hover {{ background: #2e3338; }}
QPushButton:pressed {{ background: {SURF2}; }}

QCheckBox {{ background: transparent; spacing: 7px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 8px;
    border: 2px solid {BDR_H}; background: transparent;
}}
QCheckBox::indicator:hover  {{ border-color: {DIM}; }}
QCheckBox::indicator:checked {{ background: {GRN}; border-color: {GRN}; }}

QRadioButton {{ background: transparent; spacing: 7px; color: {TEXT}; }}
QRadioButton::indicator {{
    width: 13px; height: 13px; border-radius: 7px;
    border: 2px solid {BDR_H}; background: transparent;
}}
QRadioButton::indicator:checked {{ background: {ACC}; border-color: {ACC}; }}

QSpinBox {{
    background: {BG}; border: 1px solid {BDR_H}; border-radius: 5px;
    padding: 4px 7px; color: {TEXT};
}}
QSpinBox::up-button, QSpinBox::down-button {{ background: #272b2f; border: none; width: 17px; }}

QMenu {{ background: {SURF}; border: 1px solid {BDR_H}; border-radius: 7px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; color: {TEXT}; background: transparent; }}
QMenu::item:selected {{ background: #272b2f; }}
QMenu::separator {{ height: 1px; background: {BDR}; margin: 4px 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #33383e; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #454b52; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #33383e; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

QProgressBar {{
    background: {BG}; border: 1px solid {BDR}; border-radius: 4px;
    height: 10px; text-align: center; color: {DIM}; font-size: 8pt;
}}
QProgressBar::chunk {{ background: {ACC}; border-radius: 3px; }}
"""

# ══════════════════════════════════════════════════════════════════════════════
# Small shared widgets
# ══════════════════════════════════════════════════════════════════════════════
def btn_primary(text):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: {ACC}; color: #141414; border: none; "
        f"border-radius: 5px; padding: 6px 14px; font-weight: 700; }}"
        f"QPushButton:hover {{ background: {ACC_H}; }}"
        f"QPushButton:pressed {{ background: #c07820; }}")
    return b

def btn_quiet(text):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {DIM}; border: 1px solid {BDR_H}; "
        f"border-radius: 5px; padding: 5px 12px; font-weight: 600; }}"
        f"QPushButton:hover {{ color: {TEXT}; background: #272b2f; }}")
    return b

def btn_danger(text):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {RED}; border: 1px solid {RED}; "
        f"border-radius: 5px; padding: 5px 12px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: #2e1515; }}")
    return b

def btn_icon(text, tip="", size=26, fg=DIM):
    b = QPushButton(text)
    b.setFixedSize(size, size)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {fg}; border: none; "
        f"font-size: {max(8, size - 15)}pt; padding: 0; }}"
        f"QPushButton:hover {{ color: {TEXT}; background: #272b2f; border-radius: 5px; }}")
    return b

def micro_label(text, color=DIM):
    l = QLabel(text.upper())
    f = l.font(); f.setPointSize(7); f.setBold(True); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
    l.setFont(f)
    l.setStyleSheet(f"color: {color}; background: transparent;")
    return l

def sep_line():
    f = QFrame(); f.setFixedHeight(1)
    f.setStyleSheet(f"background: {BDR}; border: none;")
    return f


class StageChip(QToolButton):
    """Coloured-dot stage chip with an instant dropdown to switch stage."""
    changed = pyqtSignal()

    def __init__(self, task, data, app=None):
        super().__init__()
        self._task, self._data, self._app = task, data, app
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCursor(Qt.PointingHandCursor)
        m = QMenu(self)
        for s in data.get("stages", []):
            act = m.addAction(s["name"]); act.setData(s["id"])
        m.triggered.connect(self._pick)
        self.setMenu(m)
        self._paint()

    def _pick(self, action):
        if self._app is not None:
            self._app.snapshot()
        self._task["stage"] = action.data()
        save_data(self._data)
        self._paint()
        self.changed.emit()

    def _paint(self):
        s = stage_by_id(self._data, self._task.get("stage"))
        self.setText(f"●  {s['name']}")
        self.setStyleSheet(
            f"QToolButton {{ background: {SURF2}; color: {TEXT}; border: 1px solid {BDR}; "
            f"border-radius: 4px; padding: 2px 8px; font-size: 8pt; }}"
            f"QToolButton:hover {{ border-color: {BDR_H}; }}"
            f"QToolButton::menu-indicator {{ width: 0; }}")
        # colour just the dot via rich text? QToolButton can't — tint whole text subtly instead
        self.setStyleSheet(self.styleSheet().replace(
            f"color: {TEXT};", f"color: {s['color']};"))


class TinyProgress(QWidget):
    def __init__(self, done, total):
        super().__init__()
        self.setFixedHeight(4)
        self._pct = 0 if total == 0 else done / total
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, e):
        from PyQt5.QtGui import QPainter, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(BG)))
        p.drawRoundedRect(0, 0, self.width(), 4, 2, 2)
        if self._pct > 0:
            p.setBrush(QBrush(QColor(GRN)))
            p.drawRoundedRect(0, 0, int(self.width() * self._pct), 4, 2, 2)

# ══════════════════════════════════════════════════════════════════════════════
# Task card — drag source + drop target
# ══════════════════════════════════════════════════════════════════════════════
MIME = "application/x-tiledo-task"

class TaskCard(QFrame):
    open_requested = pyqtSignal(dict)
    drop_action    = pyqtSignal(str, str, str)     # src_id, target_id, mode

    def __init__(self, task, data, app, allow_nest=True):
        super().__init__()
        self._task, self._data, self._app = task, data, app
        self._allow_nest = allow_nest
        self._press_pos = None
        self._dragging = False
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self._build()

    # ── content ──────────────────────────────────────────────────────────────
    def _build(self):
        pc = PRIO_COLOR.get(self._task["priority"], DIM)
        self.setObjectName("card")
        self.setStyleSheet(
            f"#card {{ background: {SURF}; border: 1px solid {BDR}; border-radius: 8px; }}"
            f"#card:hover {{ background: {SURF_H}; border-color: {BDR_H}; }}")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        stripe = QFrame(); stripe.setFixedWidth(3)
        stripe.setStyleSheet(
            f"background: {pc}; border-top-left-radius: 8px; "
            f"border-bottom-left-radius: 8px; border: none;")
        outer.addWidget(stripe)

        body = QWidget(); body.setStyleSheet("background: transparent;")
        v = QVBoxLayout(body); v.setContentsMargins(11, 9, 9, 9); v.setSpacing(5)

        top = QHBoxLayout(); top.setSpacing(3)
        title = QLabel(self._task["title"])
        title.setWordWrap(True)
        tf = title.font(); tf.setPointSize(10); tf.setBold(True); title.setFont(tf)
        title.setStyleSheet(f"color: {TEXT}; background: transparent;")
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(title, 1)

        menu_b = btn_icon("⋯", "Actions", 24)
        menu_b.clicked.connect(self._menu)
        top.addWidget(menu_b, 0, Qt.AlignTop)

        ck = QCheckBox()
        ck.setChecked(self._task.get("completed", False))
        ck.setToolTip("Complete (includes subtasks)")
        ck.stateChanged.connect(self._complete)
        top.addWidget(ck, 0, Qt.AlignTop)
        v.addLayout(top)

        kids = children_of(self._data, self._task["id"])
        pend = [k for k in kids if not k.get("completed")]
        if kids:
            done = len(kids) - len(pend)
            pr = QHBoxLayout(); pr.setSpacing(6)
            bar = TinyProgress(done, len(kids))
            bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            pr.addWidget(bar, 1)
            cnt = QLabel(f"{done}/{len(kids)}")
            cnt.setStyleSheet(f"color: {DIM}; font-size: 8pt; background: transparent;")
            pr.addWidget(cnt)
            v.addLayout(pr)
            for k in pend[:2]:
                s = stage_by_id(self._data, k.get("stage"))
                lab = QLabel(f"·  {k['title']}")
                lab.setStyleSheet(f"color: {DIM}; font-size: 8pt; background: transparent;")
                lab.setWordWrap(False)
                v.addWidget(lab)
            if len(pend) > 2:
                more = QLabel(f"·  +{len(pend) - 2} more")
                more.setStyleSheet(f"color: {FAINT}; font-size: 8pt; background: transparent;")
                v.addWidget(more)
        else:
            note = (self._task.get("notes") or "").strip().splitlines()
            if note:
                lab = QLabel(note[0][:90])
                lab.setStyleSheet(f"color: {DIM}; font-size: 8pt; font-style: italic; background: transparent;")
                lab.setWordWrap(True)
                v.addWidget(lab)

        v.addStretch()

        bottom = QHBoxLayout(); bottom.setSpacing(5)
        chip = StageChip(self._task, self._data, self._app)
        chip.changed.connect(self._app.refresh)
        bottom.addWidget(chip)
        wd = waiting_days(self._task)
        if wd is not None:
            note = (self._task.get("waiting") or {}).get("note", "")
            wchip = QLabel(f"⏳ {wd}d")
            wchip.setToolTip(f"Waiting on: {note}" if note else "Waiting")
            wchip.setStyleSheet(
                "background: #2a2010; color: #ddaa30; border: 1px solid #665500; "
                "border-radius: 4px; padding: 1px 6px; font-size: 8pt;")
            bottom.addWidget(wchip)
        bottom.addStretch()
        if kids:
            kc = QLabel(f"⊞ {len(pend)}")
            kc.setToolTip(f"{len(pend)} open subtasks")
            kc.setStyleSheet(f"color: {FAINT}; font-size: 8pt; background: transparent;")
            bottom.addWidget(kc)
        v.addLayout(bottom)
        outer.addWidget(body, 1)

        # drop indicators (hidden until a drag hovers)
        self._ind_l = QFrame(self); self._ind_r = QFrame(self)
        for f in (self._ind_l, self._ind_r):
            f.setStyleSheet(f"background: {ACC}; border-radius: 2px;")
            f.hide()

    # ── interactions ─────────────────────────────────────────────────────────
    def _complete(self, state):
        self._app.snapshot()
        cascade_complete(self._data, self._task["id"], bool(state))
        save_data(self._data)
        self._app.refresh()

    def _menu(self):
        rec = bool(self._task.get("recurring"))
        m = QMenu(self)
        if rec:
            m.addAction("Edit…").triggered.connect(self._edit)
        else:
            m.addAction("Open").triggered.connect(
                lambda _=False: self.open_requested.emit(self._task))
            m.addAction("Edit…").triggered.connect(self._edit)
            m.addAction("Add subtask…").triggered.connect(self._add_sub)
            m.addAction("Open in window").triggered.connect(
                lambda _=False: self._app.open_task_window(self._task))
            m.addSeparator()
            if self._task.get("waiting"):
                m.addAction("Clear waiting").triggered.connect(self._clear_waiting)
            else:
                m.addAction("Mark waiting…").triggered.connect(self._mark_waiting)
        m.addAction("Skip to back").triggered.connect(self._skip)
        m.addAction("Swap with queued…").triggered.connect(self._swap)
        if not rec:
            m.addSeparator()
            m.addAction("Save as template…").triggered.connect(self._save_template)
            m.addAction("Archive").triggered.connect(self._archive)
        m.addSeparator()
        m.addAction("Delete").triggered.connect(self._delete)
        m.exec_(self.mapToGlobal(self.rect().center()))

    def _mark_waiting(self):
        dlg = TextPromptDialog(self.window(), "Mark waiting",
                               "What are you waiting on?", "")
        if dlg.exec_() == QDialog.Accepted:
            self._app.snapshot()
            self._task["waiting"] = {"note": dlg.value(),
                                     "since": datetime.now().isoformat()}
            save_data(self._data)
            self._app.refresh()

    def _clear_waiting(self):
        self._app.snapshot()
        self._task.pop("waiting", None)
        save_data(self._data)
        self._app.refresh()

    def _save_template(self):
        dlg = TextPromptDialog(self.window(), "Save as template",
                               "Template name", self._task["title"])
        if dlg.exec_() == QDialog.Accepted and dlg.value():
            items = template_items_from(self._data, self._task["id"])
            if not items:
                items = [{"title": self._task["title"], "children": []}]
            self._data["templates"].append(
                {"id": str(uuid.uuid4()), "name": dlg.value(), "items": items})
            save_data(self._data)

    def _archive(self):
        n = len(descendant_ids(self._data, self._task["id"]))
        msg = f"Archive “{self._task['title']}”"
        if n: msg += f" and its {n} item{'s' if n != 1 else ''}"
        dlg = ConfirmDialog(self.window(), msg + "? You can restore it later.", "Archive")
        if dlg.exec_() == QDialog.Accepted:
            self._app.snapshot(include_archive=True)
            archive_task(self._data, self._task["id"])
            save_data(self._data)
            self._app.refresh()

    def _edit(self):
        TaskDetailDialog(self.window(), self._task, self._data, self._app).exec_()

    def _add_sub(self):
        AddTaskDialog(self.window(), self._data, self._app,
                      parent_id=self._task["id"]).exec_()

    def _skip(self):
        self._app.snapshot()
        b = bucket(self._data, self._task.get("parent_id"),
                   self._task["priority"], bool(self._task.get("recurring")))
        mx = max((t.get("order", 0) for t in b), default=0)
        self._task["order"] = mx + 10
        save_data(self._data)
        self._app.refresh()

    def _swap(self):
        SwapDialog(self.window(), self._task, self._data, self._app).exec_()

    def _delete(self):
        n = len(descendant_ids(self._data, self._task["id"]))
        msg = f"Delete “{self._task['title']}”"
        if n: msg += f" and its {n} subtask{'s' if n != 1 else ''}"
        if ConfirmDialog(self.window(), msg + "?").exec_() == QDialog.Accepted:
            self._app.snapshot()
            cascade_delete(self._data, self._task["id"])
            save_data(self._data)
            self._app.refresh()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.pos()
            self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press_pos is None or self._dragging:
            return
        if (e.pos() - self._press_pos).manhattanLength() < 10:
            return
        self._dragging = True
        drag = QDrag(self)
        mime = QMimeData()
        pref = "r" if self._task.get("recurring") else "t"
        mime.setData(MIME, f"{pref}:{self._task['id']}".encode())
        drag.setMimeData(mime)
        pm = self.grab()
        drag.setPixmap(pm.scaledToWidth(int(pm.width() * 0.85), Qt.SmoothTransformation))
        drag.setHotSpot(QPoint(20, 20))
        eff = QGraphicsOpacityEffect(self); eff.setOpacity(0.35)
        self.setGraphicsEffect(eff)
        drag.exec_(Qt.MoveAction)
        self.setGraphicsEffect(None)
        self._press_pos = None

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.LeftButton and self._press_pos is not None
                and not self._dragging):
            if self._task.get("recurring"):
                self._edit()          # recurring items have no subtree to drill into
            else:
                self.open_requested.emit(self._task)
        self._press_pos = None

    # ── drop target ──────────────────────────────────────────────────────────
    def _payload(self, e):
        if not e.mimeData().hasFormat(MIME):
            return None
        raw = bytes(e.mimeData().data(MIME)).decode()
        pref, _, tid = raw.partition(":")
        if (pref == "r") != bool(self._task.get("recurring")):
            return None                                    # recurring ↔ normal
        if tid == self._task["id"]:
            return None
        if self._task["id"] in descendant_ids(self._data, tid):
            return None                                    # would create a cycle
        return tid

    def dragEnterEvent(self, e):
        if self._payload(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        tid = self._payload(e)
        if not tid:
            e.ignore(); return
        e.acceptProposedAction()
        x, w = e.pos().x(), max(self.width(), 1)
        zone = ("before" if x < w * 0.3 else
                "after"  if x > w * 0.7 else
                ("nest" if self._allow_nest else "after"))
        self._show_zone(zone)

    def dragLeaveEvent(self, e):
        self._show_zone(None)

    def dropEvent(self, e):
        tid = self._payload(e)
        self._show_zone(None)
        if not tid:
            e.ignore(); return
        x, w = e.pos().x(), max(self.width(), 1)
        zone = ("before" if x < w * 0.3 else
                "after"  if x > w * 0.7 else
                ("nest" if self._allow_nest else "after"))
        e.acceptProposedAction()
        self.drop_action.emit(tid, self._task["id"], zone)

    def _show_zone(self, zone):
        h = self.height()
        self._ind_l.setGeometry(0, 4, 3, h - 8)
        self._ind_r.setGeometry(self.width() - 3, 4, 3, h - 8)
        self._ind_l.setVisible(zone == "before")
        self._ind_r.setVisible(zone == "after")
        if zone == "nest":
            self.setStyleSheet(
                f"#card {{ background: {SURF_H}; border: 1.5px solid {ACC}; border-radius: 8px; }}")
        else:
            self.setStyleSheet(
                f"#card {{ background: {SURF}; border: 1px solid {BDR}; border-radius: 8px; }}"
                f"#card:hover {{ background: {SURF_H}; border-color: {BDR_H}; }}")

# ══════════════════════════════════════════════════════════════════════════════
# Card grid — manual flow layout; "focus" (no scroll) or "flow" (scroll) modes
# ══════════════════════════════════════════════════════════════════════════════
class SectionHeader(QWidget):
    """Priority section label; accepts drops → moves task into that priority."""
    dropped = pyqtSignal(str, str)   # src_id, priority

    def __init__(self, priority, text, data):
        super().__init__()
        self._prio, self._data = priority, data
        self.setAcceptDrops(True)
        lay = QHBoxLayout(self); lay.setContentsMargins(2, 0, 2, 0)
        self._lab = micro_label(text, PRIO_COLOR.get(priority, DIM))
        lay.addWidget(self._lab); lay.addStretch()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            raw = bytes(e.mimeData().data(MIME)).decode()
            if raw.startswith("t:"):
                e.acceptProposedAction()
                self._lab.setStyleSheet(f"color: {TEXT}; background: transparent;")
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._lab.setStyleSheet(f"color: {PRIO_COLOR.get(self._prio, DIM)}; background: transparent;")

    def dropEvent(self, e):
        raw = bytes(e.mimeData().data(MIME)).decode()
        self.dropped.emit(raw.partition(":")[2], self._prio)
        e.acceptProposedAction()


class CardGrid(QScrollArea):
    def __init__(self, app, data, cfg, mode="focus", parent_id=None, recurring=False):
        super().__init__()
        self._app, self._data, self._cfg = app, data, cfg
        self.mode, self.parent_id, self.recurring = mode, parent_id, recurring
        self._items = []          # (widget, kind) kind: card | header | label
        self._queued_chip = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if mode == "flow" else Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._box = QWidget()
        self._box.setStyleSheet("background: transparent;")
        self.setWidget(self._box)
        QTimer.singleShot(0, self.rebuild)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    # ── data → widgets ───────────────────────────────────────────────────────
    def rebuild(self):
        for w, _ in self._items:
            w.deleteLater()
        self._items = []
        if self._queued_chip:
            self._queued_chip.deleteLater(); self._queued_chip = None

        if self.recurring:
            active = [t for t in self._data["tasks"]
                      if t.get("recurring") and not t.get("completed")]
            done = [t for t in self._data["tasks"]
                    if t.get("recurring") and t.get("completed")]
            active.sort(key=lambda t: t.get("order", 0))
            if active or done:
                self._add_header(None, f"Active · {len(active)}")
                for t in active: self._add_card(t, allow_nest=False)
                if done:
                    self._add_header(None, f"Done · {len(done)}")
                    for t in done: self._add_card(t, allow_nest=False)
            else:
                self._add_empty("No recurring tasks yet — add one above.")
        elif self.mode == "focus":
            any_items = False
            for prio in ("high", "medium", "low"):
                items = bucket(self._data, None, prio)
                if not items: continue
                any_items = True
                self._add_header(prio, f"{PRIO_LABEL[prio]} · {len(items)}")
                for t in items: self._add_card(t)
            if not any_items:
                self._add_empty("All clear ✓\nAdd a task above to get started.")
        else:  # flow — children of parent_id
            items = children_of(self._data, self.parent_id, include_done=False)
            for t in items: self._add_card(t)
            if not items:
                self._add_empty("Nothing here yet — add items above,\nor drag cards in to group them.")
        self._relayout()

    def _add_card(self, t, allow_nest=True):
        c = TaskCard(t, self._data, self._app, allow_nest=allow_nest and not self.recurring)
        c.setParent(self._box)
        c.open_requested.connect(self._app.open_task)
        c.drop_action.connect(self._app.handle_drop)
        c.hide()
        self._items.append((c, "card"))

    def _add_header(self, prio, text):
        if prio:
            h = SectionHeader(prio, text, self._data)
            h.dropped.connect(self._app.handle_priority_drop)
        else:
            h = QWidget(); lay = QHBoxLayout(h); lay.setContentsMargins(2, 0, 2, 0)
            lay.addWidget(micro_label(text)); lay.addStretch()
        h.setParent(self._box); h.hide()
        self._items.append((h, "header"))

    def _add_empty(self, text):
        l = QLabel(text)
        l.setAlignment(Qt.AlignCenter)
        l.setStyleSheet(f"color: {FAINT}; font-size: 12pt; background: transparent;")
        l.setParent(self._box); l.hide()
        self._items.append((l, "empty"))

    # ── widgets → geometry ───────────────────────────────────────────────────
    def _relayout(self):
        vw = self.viewport().width()
        vh = self.viewport().height()
        if vw < 80 or not self._items:
            return
        m, g = 12, 10
        base = max(150, self._cfg.get("tile_size", 230))
        cols = max(1, (vw - 2 * m + g) // (base + g))
        cw = (vw - 2 * m - g * (cols - 1)) // cols
        ch = max(110, int(cw * 0.66))

        y, col = m, 0
        hidden = 0
        limit_h = vh if self.mode == "focus" else 10 ** 9

        for w, kind in self._items:
            if kind in ("header", "empty"):
                if col > 0:
                    y += ch + g; col = 0
                if kind == "empty":
                    w.setGeometry(0, 0, vw, max(vh, 120)); w.show()
                    y = max(vh, 120)
                    continue
                if y + 20 > limit_h:
                    w.hide(); continue
                w.setGeometry(m, y, vw - 2 * m, 18); w.show()
                y += 18 + 6
            else:
                x = m + col * (cw + g)
                if y + ch > limit_h:
                    w.hide(); hidden += 1; continue
                w.setGeometry(x, y, cw, ch); w.show()
                col += 1
                if col >= cols:
                    col = 0; y += ch + g

        total_h = y + (ch + g if col > 0 else 0) + m
        self._box.setMinimumHeight(total_h if self.mode == "flow" else 0)

        if self.mode == "focus" and hidden:
            if self._queued_chip is None:
                self._queued_chip = QLabel(self._box)
                self._queued_chip.setStyleSheet(
                    f"background: {SURF2}; color: {DIM}; border: 1px solid {BDR}; "
                    f"border-radius: 9px; padding: 2px 10px; font-size: 8pt;")
            self._queued_chip.setText(f"+{hidden} queued")
            self._queued_chip.adjustSize()
            self._queued_chip.move(vw - self._queued_chip.width() - 14,
                                   vh - self._queued_chip.height() - 8)
            self._queued_chip.show()
        elif self._queued_chip:
            self._queued_chip.hide()

# ══════════════════════════════════════════════════════════════════════════════
# Breadcrumb — navigation trail; crumbs accept drops (move task up the tree)
# ══════════════════════════════════════════════════════════════════════════════
class Crumb(QPushButton):
    dropped = pyqtSignal(str, object)   # src_id, parent_id-or-None

    def __init__(self, text, pid):
        super().__init__(text)
        self._pid = pid
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {DIM}; border: none; "
            f"padding: 3px 6px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {ACC}; }}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME) and bytes(e.mimeData().data(MIME)).decode().startswith("t:"):
            e.acceptProposedAction()

    def dropEvent(self, e):
        raw = bytes(e.mimeData().data(MIME)).decode()
        self.dropped.emit(raw.partition(":")[2], self._pid)
        e.acceptProposedAction()


class Breadcrumb(QWidget):
    navigate = pyqtSignal(object)        # parent_id or None
    move_to  = pyqtSignal(str, object)   # src_id, parent_id

    def __init__(self):
        super().__init__()
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0); self._lay.setSpacing(0)

    def set_path(self, data, parent_id):
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        chain = []
        if parent_id:
            chain = ancestor_chain(data, parent_id) + [task_by_id(data, parent_id)]
            chain = [c for c in chain if c]
        crumbs = [("Tasks", None)] + [(t["title"], t["id"]) for t in chain]
        for i, (label, pid) in enumerate(crumbs):
            c = Crumb(label if len(label) < 30 else label[:28] + "…", pid)
            c.clicked.connect(lambda _=False, p=pid: self.navigate.emit(p))
            c.dropped.connect(self.move_to)
            if i == len(crumbs) - 1:
                c.setStyleSheet(c.styleSheet().replace(f"color: {DIM}", f"color: {TEXT}"))
            self._lay.addWidget(c)
            if i < len(crumbs) - 1:
                s = QLabel("▸"); s.setStyleSheet(f"color: {FAINT}; background: transparent; padding: 0 1px;")
                self._lay.addWidget(s)
        self._lay.addStretch()

# ══════════════════════════════════════════════════════════════════════════════
# Frameless chrome: DragBar + BaseDialog
# ══════════════════════════════════════════════════════════════════════════════
class DragBar(QWidget):
    def __init__(self, title, win, height=42, minimize=True):
        super().__init__()
        self._win, self._dp = win, None
        self.setFixedHeight(height)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0); lay.setSpacing(6)
        dot = QLabel("●"); dot.setStyleSheet(f"color: {ACC}; background: transparent; font-size: 8pt;")
        lay.addWidget(dot)
        self._title = QLabel(title)
        tf = self._title.font(); tf.setPointSize(10); tf.setBold(True)
        self._title.setFont(tf)
        self._title.setStyleSheet(f"color: {TEXT}; background: transparent; letter-spacing: 0.5px;")
        lay.addWidget(self._title)
        lay.addStretch()
        self._meta = QLabel("")
        self._meta.setStyleSheet(f"color: {DIM}; font-size: 8pt; background: transparent;")
        lay.addWidget(self._meta)
        self.center_slot = lay   # dialogs can insert extra buttons
        if minimize:
            mb = btn_icon("—", "Minimise", 30)
            mb.clicked.connect(win.showMinimized)
            lay.addWidget(mb)
        cb = btn_icon("✕", "Close", 30)
        cb.setStyleSheet(cb.styleSheet().replace("#272b2f", "#3a1515")
                         .replace(f"color: {TEXT}", "color: #e07070"))
        cb.clicked.connect(win.close)
        lay.addWidget(cb)

    def set_meta(self, t): self._meta.setText(t)
    def set_title(self, t): self._title.setText(t)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dp = e.globalPos() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._dp:
            self._win.move(e.globalPos() - self._dp)

    def mouseReleaseEvent(self, e): self._dp = None

    def mouseDoubleClickEvent(self, e):
        if self._win.isMaximized(): self._win.showNormal()
        else: self._win.showMaximized()


class BaseDialog(QDialog):
    def __init__(self, parent, title, w=480, h=520):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(w, h)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        frame = QFrame(); frame.setObjectName("dlg")
        frame.setStyleSheet(
            f"#dlg {{ background: {BG}; border: 1px solid {BDR_H}; border-radius: 10px; }}")
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(28); sh.setColor(QColor(0, 0, 0, 190)); sh.setOffset(0, 4)
        frame.setGraphicsEffect(sh)
        outer.addWidget(frame)
        fl = QVBoxLayout(frame); fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(0)
        self.bar = DragBar(title, self, 38, minimize=False)
        self.bar.setStyleSheet(
            f"DragBar {{ background: {NAV}; border-top-left-radius: 10px; "
            f"border-top-right-radius: 10px; border-bottom: 1px solid {BDR}; }}")
        fl.addWidget(self.bar)
        self.body = QWidget(); self.body.setStyleSheet("background: transparent;")
        self._bl = QVBoxLayout(self.body)
        self._bl.setContentsMargins(18, 14, 18, 16); self._bl.setSpacing(9)
        fl.addWidget(self.body, 1)

    def add(self, w): self._bl.addWidget(w)
    def add_lay(self, l): self._bl.addLayout(l)
    def add_stretch(self): self._bl.addStretch()


class ConfirmDialog(BaseDialog):
    def __init__(self, parent, text, ok_label="Delete"):
        super().__init__(parent, "Confirm", 400, 170)
        lab = QLabel(text); lab.setWordWrap(True)
        self.add(lab); self.add_stretch()
        row = QHBoxLayout()
        ok = btn_danger(ok_label); ok.clicked.connect(self.accept)
        no = btn_quiet("Cancel"); no.clicked.connect(self.reject)
        row.addStretch(); row.addWidget(no); row.addWidget(ok)
        self.add_lay(row)


class TextPromptDialog(BaseDialog):
    def __init__(self, parent, title, label, initial=""):
        super().__init__(parent, title, 400, 170)
        self.add(micro_label(label))
        self._edit = QLineEdit(initial)
        self._edit.returnPressed.connect(self.accept)
        self.add(self._edit); self.add_stretch()
        row = QHBoxLayout()
        ok = btn_primary("OK"); ok.clicked.connect(self.accept)
        no = btn_quiet("Cancel"); no.clicked.connect(self.reject)
        row.addStretch(); row.addWidget(no); row.addWidget(ok)
        self.add_lay(row)
        self._edit.setFocus(); self._edit.selectAll()

    def value(self): return self._edit.text().strip()

# ══════════════════════════════════════════════════════════════════════════════
# Add / edit task dialogs
# ══════════════════════════════════════════════════════════════════════════════
def _prio_row(selected="medium"):
    lay = QHBoxLayout(); lay.setSpacing(10)
    grp = QButtonGroup()
    for p in ("high", "medium", "low"):
        rb = QRadioButton(PRIO_LABEL[p])
        rb.setProperty("v", p)
        rb.setStyleSheet(f"color: {PRIO_COLOR[p]}; font-weight: 600; background: transparent;")
        rb.setChecked(p == selected)
        grp.addButton(rb); lay.addWidget(rb)
    lay.addStretch()
    return lay, grp


class AddTaskDialog(BaseDialog):
    def __init__(self, parent, data, app, parent_id=None, recurring=False):
        t = "Add recurring task" if recurring else ("Add subtask" if parent_id else "Add task")
        super().__init__(parent, t, 440, 360)
        self._data, self._app = data, app
        self._pid, self._rec = parent_id, recurring
        self.add(micro_label("Title"))
        self._title = QLineEdit(); self._title.setPlaceholderText("What needs doing?")
        self._title.returnPressed.connect(self._save)
        self.add(self._title)
        self.add(micro_label("Priority"))
        pl, self._grp = _prio_row(); self.add_lay(pl)
        if not recurring:
            self.add(micro_label("Stage"))
            self._stage = QComboBox()
            for s in data.get("stages", []): self._stage.addItem(s["name"], s["id"])
            self.add(self._stage)
        else:
            self._stage = None
        self._tpl = None
        if not recurring and data.get("templates"):
            self.add(micro_label("Template"))
            self._tpl = QComboBox()
            self._tpl.addItem("— none —", None)
            for tp in data["templates"]:
                self._tpl.addItem(
                    f"{tp['name']}  ({count_template_items(tp.get('items', []))} items)",
                    tp["id"])
            self.add(self._tpl)
        self.add(micro_label("Notes (optional)"))
        self._notes = QTextEdit(); self._notes.setFixedHeight(64)
        self.add(self._notes); self.add_stretch()
        row = QHBoxLayout()
        ok = btn_primary("Add"); ok.clicked.connect(self._save)
        no = btn_quiet("Cancel"); no.clicked.connect(self.reject)
        row.addStretch(); row.addWidget(no); row.addWidget(ok)
        self.add_lay(row)
        self._title.setFocus()

    def _save(self):
        title = self._title.text().strip()
        if not title: return
        self._app.snapshot()
        ch = self._grp.checkedButton()
        t = mk_task(title, ch.property("v") if ch else "medium", self._pid, self._rec)
        if self._stage: t["stage"] = self._stage.currentData()
        t["notes"] = self._notes.toPlainText()
        b = bucket(self._data, self._pid, t["priority"], self._rec)
        t["order"] = (max((x.get("order", 0) for x in b), default=-10)) + 10
        self._data["tasks"].append(t)
        if self._tpl is not None and self._tpl.currentData():
            tp = next((x for x in self._data["templates"]
                       if x["id"] == self._tpl.currentData()), None)
            if tp:
                instantiate_items(self._data, tp.get("items", []),
                                  t["id"], t["priority"])
        save_data(self._data)
        self._app.refresh()
        self.accept()


class TaskDetailDialog(BaseDialog):
    def __init__(self, parent, task, data, app):
        super().__init__(parent, "Edit task", 460, 540)
        self._task, self._data, self._app = task, data, app
        self.add(micro_label("Title"))
        self._title = QLineEdit(task["title"])
        self.add(self._title)
        self.add(micro_label("Priority"))
        pl, self._grp = _prio_row(task["priority"]); self.add_lay(pl)
        self.add(micro_label("Stage"))
        self._stage = QComboBox()
        for s in data.get("stages", []):
            self._stage.addItem(s["name"], s["id"])
            if s["id"] == task.get("stage"):
                self._stage.setCurrentIndex(self._stage.count() - 1)
        self.add(self._stage)
        self.add(micro_label("Waiting on  (leave blank if not waiting)"))
        w = task.get("waiting") or {}
        self._waiting = QLineEdit(w.get("note", ""))
        wd = waiting_days(task)
        if wd is not None:
            self._waiting.setToolTip(f"Waiting for {wd} day{'s' if wd != 1 else ''}")
        self.add(self._waiting)
        self.add(micro_label("Notes"))
        self._notes = QTextEdit(task.get("notes", ""))
        self._notes.setMinimumHeight(100)
        self.add(self._notes)
        row = QHBoxLayout()
        de = btn_danger("Delete"); de.clicked.connect(self._delete)
        ok = btn_primary("Save"); ok.clicked.connect(self._save)
        no = btn_quiet("Cancel"); no.clicked.connect(self.reject)
        row.addWidget(de); row.addStretch(); row.addWidget(no); row.addWidget(ok)
        self.add_lay(row)
        self._title.setFocus()

    def _save(self):
        self._app.snapshot()
        t = self._title.text().strip()
        if t: self._task["title"] = t
        ch = self._grp.checkedButton()
        if ch: self._task["priority"] = ch.property("v")
        self._task["stage"] = self._stage.currentData()
        self._task["notes"] = self._notes.toPlainText()
        wnote = self._waiting.text().strip()
        old = self._task.get("waiting") or {}
        if not wnote:
            self._task.pop("waiting", None)
        elif wnote != old.get("note"):
            self._task["waiting"] = {"note": wnote,
                                     "since": datetime.now().isoformat()}
        save_data(self._data)
        self._app.refresh()
        self.accept()

    def _delete(self):
        n = len(descendant_ids(self._data, self._task["id"]))
        msg = f"Delete “{self._task['title']}”"
        if n: msg += f" and its {n} subtask{'s' if n != 1 else ''}"
        if ConfirmDialog(self, msg + "?").exec_() == QDialog.Accepted:
            self._app.snapshot()
            cascade_delete(self._data, self._task["id"])
            save_data(self._data)
            self._app.refresh()
            self.accept()


class SwapDialog(BaseDialog):
    """Swap this card's queue position with another pending task of the same priority."""
    def __init__(self, parent, cur, data, app):
        super().__init__(parent, "Swap with queued task", 520, 480)
        self._cur, self._data, self._app = cur, data, app
        hint = QLabel("Pick a task to trade places with — it takes this card's slot.")
        hint.setWordWrap(True); hint.setStyleSheet(f"color: {DIM};")
        self.add(hint)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        box = QWidget(); box.setStyleSheet("background: transparent;")
        v = QVBoxLayout(box); v.setContentsMargins(0, 4, 0, 4); v.setSpacing(4)
        peers = [t for t in bucket(data, cur.get("parent_id"), cur["priority"],
                                   bool(cur.get("recurring")))
                 if t["id"] != cur["id"]]
        if not peers:
            v.addWidget(QLabel("No other tasks at this priority."))
        for t in peers:
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background: {SURF}; border: 1px solid {BDR}; border-radius: 6px; }}"
                              f"QFrame:hover {{ border-color: {BDR_H}; }}")
            rl = QHBoxLayout(row); rl.setContentsMargins(9, 5, 6, 5)
            lab = QLabel(t["title"]); lab.setStyleSheet("background: transparent;")
            rl.addWidget(lab, 1)
            pick = btn_quiet("Swap")
            pick.clicked.connect(lambda _=False, other=t: self._do(other))
            rl.addWidget(pick)
            v.addWidget(row)
        v.addStretch()
        sc.setWidget(box)
        self.add(sc)
        c = btn_quiet("Cancel"); c.clicked.connect(self.reject)
        r = QHBoxLayout(); r.addStretch(); r.addWidget(c)
        self.add_lay(r)

    def _do(self, other):
        self._app.snapshot()
        self._cur["order"], other["order"] = other.get("order", 0), self._cur.get("order", 0)
        save_data(self._data)
        self._app.refresh()
        self.accept()

# ══════════════════════════════════════════════════════════════════════════════
# All-tasks tree overview
# ══════════════════════════════════════════════════════════════════════════════
class AllTasksDialog(BaseDialog):
    def __init__(self, parent, data, app):
        super().__init__(parent, "All tasks", 660, 640)
        self._data, self._app = data, app
        arc = btn_quiet("View archive")
        arc.clicked.connect(lambda _=False: self._app._track(
            ArchiveDialog(self, self._data, self._app)))
        self.bar.center_slot.insertWidget(self.bar.center_slot.count() - 1, arc)
        clear = btn_quiet("Archive completed")
        clear.clicked.connect(self._clear_done)
        self.bar.center_slot.insertWidget(self.bar.center_slot.count() - 1, clear)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        self._box = QWidget(); self._box.setStyleSheet("background: transparent;")
        self._v = QVBoxLayout(self._box)
        self._v.setContentsMargins(0, 2, 0, 2); self._v.setSpacing(3)
        sc.setWidget(self._box)
        self.add(sc)
        self._render()

    def _render(self):
        while self._v.count():
            it = self._v.takeAt(0)
            if it.widget(): it.widget().deleteLater()

        def emit_rows(pid, level):
            for t in children_of(self._data, pid):
                self._v.addWidget(self._row(t, level))
                emit_rows(t["id"], level + 1)

        roots = children_of(self._data, None)
        if roots:
            self._v.addWidget(micro_label("Tasks"))
            emit_rows(None, 0)
        rec = [t for t in self._data["tasks"] if t.get("recurring")]
        if rec:
            self._v.addWidget(micro_label("Recurring"))
            for t in sorted(rec, key=lambda x: (x.get("completed", False), x.get("order", 0))):
                self._v.addWidget(self._row(t, 0))
        if not roots and not rec:
            e = QLabel("Nothing yet."); e.setStyleSheet(f"color: {FAINT};")
            self._v.addWidget(e)
        self._v.addStretch()

    def _row(self, t, level):
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {SURF}; border: 1px solid {BDR}; border-radius: 6px; }}"
            f"QFrame:hover {{ border-color: {BDR_H}; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8 + level * 20, 4, 8, 4); rl.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {PRIO_COLOR.get(t['priority'], DIM)}; "
                          f"font-size: 7pt; background: transparent;")
        rl.addWidget(dot)
        ck = QCheckBox(); ck.setChecked(t.get("completed", False))

        def tog(state, task=t):
            self._app.snapshot()
            cascade_complete(self._data, task["id"], bool(state))
            save_data(self._data)
            self._app.refresh()
            self._render()
        ck.stateChanged.connect(tog)
        rl.addWidget(ck)
        lab = QLabel(t["title"])
        style = f"color: {DIM if t.get('completed') else TEXT}; background: transparent;"
        if t.get("completed"): style += " text-decoration: line-through;"
        lab.setStyleSheet(style)
        lab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        rl.addWidget(lab)
        ed = btn_icon("✎", "Edit", 24)

        def do_edit(_=False, task=t):
            dlg = TaskDetailDialog(self, task, self._data, self._app)
            dlg.exec_()
            self._render()
        ed.clicked.connect(do_edit)
        rl.addWidget(ed)
        return row

    def _clear_done(self):
        done_roots = [t for t in self._data["tasks"]
                      if t.get("completed") and not t.get("recurring")
                      and t.get("parent_id") is None]
        if not done_roots:
            return
        if ConfirmDialog(self, f"Archive {len(done_roots)} completed task(s) "
                               f"and their subtasks? You can restore them later.",
                         "Archive").exec_() == QDialog.Accepted:
            self._app.snapshot(include_archive=True)
            for t in done_roots:
                archive_task(self._data, t["id"])
            save_data(self._data)
            self._app.refresh()
            self._render()


# ══════════════════════════════════════════════════════════════════════════════
# Archive browser — search, restore, delete forever
# ══════════════════════════════════════════════════════════════════════════════
class ArchiveDialog(BaseDialog):
    def __init__(self, parent, data, app):
        super().__init__(parent, "Archive", 620, 600)
        self._data, self._app = data, app
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search archive…")
        self._search.textChanged.connect(self._render)
        self.add(self._search)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        self._box = QWidget(); self._box.setStyleSheet("background: transparent;")
        self._v = QVBoxLayout(self._box)
        self._v.setContentsMargins(0, 2, 0, 2); self._v.setSpacing(4)
        sc.setWidget(self._box)
        self.add(sc)
        self._render()

    def _render(self):
        while self._v.count():
            it = self._v.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        a = load_archive()
        q = self._search.text().strip().lower()
        roots = [t for t in a["tasks"] if t.get("archived_at")]
        roots.sort(key=lambda t: t.get("archived_at", ""), reverse=True)
        shown = 0
        for r in roots:
            ids = _archive_subtree_ids(a, r["id"])
            if q:
                sub = [t for t in a["tasks"] if t["id"] in ids]
                hay = " ".join(t["title"].lower() + " " + (t.get("notes") or "").lower()
                               for t in sub)
                if q not in hay:
                    continue
            self._v.addWidget(self._row(r, len(ids) - 1))
            shown += 1
        if not shown:
            e = QLabel("Archive is empty." if not q else f"No matches for “{q}”.")
            e.setStyleSheet(f"color: {FAINT};")
            e.setAlignment(Qt.AlignCenter)
            self._v.addWidget(e)
        self._v.addStretch()

    def _row(self, r, n_children):
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {SURF}; border: 1px solid {BDR}; border-radius: 6px; }}"
            f"QFrame:hover {{ border-color: {BDR_H}; }}")
        rl = QHBoxLayout(row); rl.setContentsMargins(10, 6, 6, 6); rl.setSpacing(8)
        col = QVBoxLayout(); col.setSpacing(1)
        tl = QLabel(r["title"])
        tf = tl.font(); tf.setBold(True); tl.setFont(tf)
        tl.setStyleSheet("background: transparent;")
        col.addWidget(tl)
        when = (r.get("archived_at") or "")[:10]
        sub = QLabel(f"{n_children} item{'s' if n_children != 1 else ''} · archived {when}")
        sub.setStyleSheet(f"color: {FAINT}; font-size: 8pt; background: transparent;")
        col.addWidget(sub)
        rl.addLayout(col, 1)
        rs = btn_quiet("Restore")
        rs.clicked.connect(lambda _=False, rid=r["id"]: self._restore(rid))
        rl.addWidget(rs)
        de = btn_danger("Delete")
        de.clicked.connect(lambda _=False, rid=r["id"], title=r["title"]: self._delete(rid, title))
        rl.addWidget(de)
        return row

    def _restore(self, rid):
        self._app.snapshot(include_archive=True)
        restore_archived(self._data, rid)
        save_data(self._data)
        self._app.refresh()
        self._render()

    def _delete(self, rid, title):
        if ConfirmDialog(self, f"Permanently delete “{title}” from the archive? "
                               f"This cannot be undone later.").exec_() == QDialog.Accepted:
            self._app.snapshot(include_archive=True)
            delete_archived(rid)
            self._render()

# ══════════════════════════════════════════════════════════════════════════════
# Pop-out task window (non-modal, tracked, own drill navigation)
# ══════════════════════════════════════════════════════════════════════════════
class TaskWindow(BaseDialog):
    def __init__(self, parent, task, data, cfg, app):
        super().__init__(parent, task["title"][:46], 760, 540)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)   # independent window
        self._data, self._cfg, self._app = data, cfg, app
        self._root = task["id"]
        self._pid = task["id"]
        back = btn_icon("←", "Back", 26)
        back.clicked.connect(self._back)
        self.bar.center_slot.insertWidget(2, back)
        self._quick = QLineEdit()
        self._quick.setPlaceholderText("＋  Add item…  (Enter)")
        self._quick.returnPressed.connect(self._quick_add)
        self.add(self._quick)
        self._grid = CardGrid(self._winproxy(), data, cfg, mode="flow", parent_id=self._pid)
        self.add(self._grid)

    def _winproxy(self):
        """The grid talks to an app-like object; reroute open() into this window."""
        outer = self
        class Proxy:
            def refresh(self): outer._app.refresh()
            def open_task(self, task): outer._open(task)
            def handle_drop(self, s, t, m): outer._app.handle_drop(s, t, m)
            def handle_priority_drop(self, s, p): outer._app.handle_priority_drop(s, p)
            def open_task_window(self, task): outer._app.open_task_window(task)
            def snapshot(self, **kw): outer._app.snapshot(**kw)
            def _track(self, dlg): outer._app._track(dlg)
        return Proxy()

    def _open(self, task):
        self._pid = task["id"]
        self._grid.parent_id = task["id"]
        self.bar.set_title(task["title"][:46])
        self._grid.rebuild()

    def _back(self):
        t = task_by_id(self._data, self._pid)
        up = t.get("parent_id") if t else None
        if self._pid == self._root or up is None and self._pid == self._root:
            return
        self._pid = up if up is not None else self._root
        pt = task_by_id(self._data, self._pid)
        self.bar.set_title((pt["title"] if pt else "Tasks")[:46])
        self._grid.parent_id = self._pid
        self._grid.rebuild()

    def _quick_add(self):
        title = self._quick.text().strip()
        if not title: return
        self._app.snapshot()
        t = mk_task(title, "medium", self._pid)
        b = bucket(self._data, self._pid, "medium")
        t["order"] = (max((x.get("order", 0) for x in b), default=-10)) + 10
        self._data["tasks"].append(t)
        save_data(self._data)
        self._quick.clear()
        self._app.refresh()

    def _render(self):
        # if our current node was deleted, climb to the root task or close
        if task_by_id(self._data, self._pid) is None:
            if task_by_id(self._data, self._root) is None:
                self.close(); return
            self._pid = self._root
            self._grid.parent_id = self._root
        self._grid.rebuild()

# ══════════════════════════════════════════════════════════════════════════════
# Notes — sidebar pages + rich editor with image paste / drag-resize
# ══════════════════════════════════════════════════════════════════════════════
class _ImageHandle(QWidget):
    def __init__(self, viewport, editor, img_pos, img_w, anchor_rect):
        super().__init__(viewport)
        self._editor, self._img_pos = editor, img_pos
        self._drag_from, self._start_w = None, img_w
        self.setFixedSize(14, 14)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setStyleSheet(f"background: {ACC}; border: 1px solid #111; border-radius: 3px;")
        x = min(anchor_rect.left() + img_w - 7, viewport.width() - 15)
        y = min(anchor_rect.top() + anchor_rect.height() - 7, viewport.height() - 15)
        self.move(max(0, x), max(0, y))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_from = e.globalPos()
            self._start_w = self._width_now()

    def mouseMoveEvent(self, e):
        if self._drag_from:
            self._apply(max(48, self._start_w + e.globalPos().x() - self._drag_from.x()))

    def mouseReleaseEvent(self, e): self._drag_from = None

    def _cursor(self):
        c = QTextCursor(self._editor.document())
        c.setPosition(self._img_pos)
        return c

    def _width_now(self):
        try:
            w = int(self._cursor().charFormat().toImageFormat().width())
            return w or 400
        except Exception:
            return 400

    def _apply(self, w):
        c = self._cursor()
        fmt = c.charFormat().toImageFormat()
        fmt.setWidth(w)
        c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
        c.mergeCharFormat(fmt)
        r = self._editor.cursorRect(self._cursor())
        self.move(max(0, min(r.left() + w - 7, self.parent().width() - 15)), self.y())


class NotesEditor(QTextEdit):
    """Rich editor: paste images from clipboard, click an image for a resize grip."""
    def __init__(self):
        super().__init__()
        self._handle = None
        self.setAcceptRichText(True)
        self.viewport().installEventFilter(self)

    def insertFromMimeData(self, source):
        if source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                buf = QBuffer(); buf.open(QIODevice.WriteOnly)
                img.save(buf, "PNG")
                b64 = base64.b64encode(bytes(buf.data())).decode()
                w = min(480, img.width())
                self.insertHtml(f'<img src="data:image/png;base64,{b64}" width="{w}"><br>')
                return
        super().insertFromMimeData(source)

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.MouseButtonPress \
                and event.button() == Qt.LeftButton:
            if self._handle:
                self._handle.deleteLater(); self._handle = None
            cur = self.cursorForPosition(event.pos())
            img_cur = self._find_image(cur)
            if img_cur is not None:
                fmt = img_cur.charFormat().toImageFormat()
                try: w = int(fmt.width()) or 400
                except Exception: w = 400
                r = self.cursorRect(img_cur)
                self._handle = _ImageHandle(self.viewport(), self,
                                            img_cur.position(), w, r)
                self._handle.show()
        return False

    def _find_image(self, cursor):
        doc = self.document()
        for p in (cursor.position(), cursor.position() - 1):
            if 0 <= p < doc.characterCount() and ord(doc.characterAt(p)) == 0xFFFC:
                c = QTextCursor(doc); c.setPosition(p)
                return c
        return None

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self._handle:
            self._handle.deleteLater(); self._handle = None

    def insert_ref_table(self, rows, cols):
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderBrush(QColor(BDR_H))
        try:
            fmt.setBorderCollapse(True)
        except AttributeError:
            pass
        fmt.setCellPadding(5)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
        self.textCursor().insertTable(rows, cols, fmt)

    def contextMenuEvent(self, e):
        m = self.createStandardContextMenu()
        cur = self.cursorForPosition(e.pos())
        table = cur.currentTable()
        if table:
            cell = table.cellAt(cur)
            m.addSeparator()
            m.addAction("Insert row below").triggered.connect(
                lambda _=False: table.insertRows(cell.row() + 1, 1))
            m.addAction("Insert column right").triggered.connect(
                lambda _=False: table.insertColumns(cell.column() + 1, 1))
            m.addAction("Delete row").triggered.connect(
                lambda _=False: table.removeRows(cell.row(), 1))
            m.addAction("Delete column").triggered.connect(
                lambda _=False: table.removeColumns(cell.column(), 1))
        m.exec_(e.globalPos())


class TableDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "Insert table", 320, 200)
        row = QHBoxLayout()
        row.addWidget(QLabel("Rows:"))
        self._rows = QSpinBox(); self._rows.setRange(1, 30); self._rows.setValue(3)
        row.addWidget(self._rows)
        row.addSpacing(14)
        row.addWidget(QLabel("Columns:"))
        self._cols = QSpinBox(); self._cols.setRange(1, 12); self._cols.setValue(3)
        row.addWidget(self._cols)
        row.addStretch()
        self.add_lay(row)
        hint = QLabel("Right-click inside a table to add or remove rows and columns.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {FAINT}; font-size: 8pt;")
        self.add(hint)
        self.add_stretch()
        br = QHBoxLayout()
        ok = btn_primary("Insert"); ok.clicked.connect(self.accept)
        no = btn_quiet("Cancel"); no.clicked.connect(self.reject)
        br.addStretch(); br.addWidget(no); br.addWidget(ok)
        self.add_lay(br)

    def dims(self):
        return self._rows.value(), self._cols.value()


class NotesView(QWidget):
    def __init__(self, notes, app):
        super().__init__()
        self._notes, self._app = notes, app
        self._cur = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.flush)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # sidebar
        side = QFrame()
        side.setFixedWidth(190)
        side.setStyleSheet(f"QFrame {{ background: {NAV}; border-right: 1px solid {BDR}; }}")
        sv = QVBoxLayout(side); sv.setContentsMargins(8, 8, 8, 8); sv.setSpacing(5)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search pages…")
        self._search.textChanged.connect(self._render_pages)
        sv.addWidget(self._search)
        self._page_scroll = QScrollArea()
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setFrameShape(QFrame.NoFrame)
        self._page_box = QWidget(); self._page_box.setStyleSheet("background: transparent;")
        self._page_v = QVBoxLayout(self._page_box)
        self._page_v.setContentsMargins(0, 0, 0, 0); self._page_v.setSpacing(3)
        self._page_scroll.setWidget(self._page_box)
        sv.addWidget(self._page_scroll, 1)
        addp = btn_quiet("＋ New page")
        addp.clicked.connect(self._add_page)
        sv.addWidget(addp)
        lay.addWidget(side)

        # editor column
        col = QVBoxLayout(); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(0)
        tb = QFrame()
        tb.setStyleSheet(f"QFrame {{ background: {SURF2}; border-bottom: 1px solid {BDR}; }}")
        tl = QHBoxLayout(tb); tl.setContentsMargins(8, 3, 8, 3); tl.setSpacing(1)
        for text, tip, fn in (
            ("H1", "Heading 1", lambda: self._heading(16)),
            ("H2", "Heading 2", lambda: self._heading(13)),
            ("H3", "Heading 3", lambda: self._heading(11)),
            ("B",  "Bold  (Ctrl+B)", self._bold),
            ("I",  "Italic  (Ctrl+I)", self._italic),
            ("U",  "Underline", self._underline),
            ("•",  "Bullet list", self._bullet),
            ("▦",  "Insert table", self._table),
            ("🖼", "Insert image (or just paste one)", self._image),
            ("Aa", "Normal text", self._normal),
        ):
            b = btn_icon(text, tip, 30)
            b.clicked.connect(lambda _=False, f=fn: f())
            tl.addWidget(b)
        tl.addStretch()
        col.addWidget(tb)
        self._editor = NotesEditor()
        self._editor.setStyleSheet(
            f"QTextEdit {{ background: {BG}; border: none; padding: 14px; font-size: 10pt; }}")
        self._editor.textChanged.connect(lambda: self._save_timer.start(700))
        col.addWidget(self._editor, 1)
        wrap = QWidget(); wrap.setLayout(col)
        wrap.setStyleSheet("background: transparent;")
        lay.addWidget(wrap, 1)

        QShortcut(QKeySequence.Bold, self._editor, activated=self._bold)
        QShortcut(QKeySequence.Italic, self._editor, activated=self._italic)

        self._render_pages()
        tabs = self._notes["tabs"]
        if tabs: self._select(tabs[0]["id"])

    # ── pages ────────────────────────────────────────────────────────────────
    def _render_pages(self):
        while self._page_v.count():
            it = self._page_v.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        q = self._search.text().strip().lower()
        for tab in self._notes["tabs"]:
            if q:
                plain = re.sub(r"<[^>]+>", " ", tab.get("html", "")).lower()
                if q not in tab["name"].lower() and q not in plain:
                    continue
            self._page_v.addWidget(self._page_row(tab))
        self._page_v.addStretch()

    def _page_row(self, tab):
        row = QFrame()
        active = tab["id"] == self._cur
        row.setStyleSheet(
            f"QFrame {{ background: {'#272b2f' if active else 'transparent'}; "
            f"border: none; border-radius: 5px; }}"
            f"QFrame:hover {{ background: #232729; }}")
        rl = QHBoxLayout(row); rl.setContentsMargins(4, 1, 2, 1); rl.setSpacing(2)
        b = QPushButton(tab["name"])
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; text-align: left; "
            f"color: {ACC if active else DIM}; font-weight: {'700' if active else '500'}; "
            f"padding: 5px 4px; }}"
            f"QPushButton:hover {{ color: {TEXT}; }}")
        b.clicked.connect(lambda _=False, tid=tab["id"]: self._select(tid))
        rl.addWidget(b, 1)
        rn = btn_icon("✎", "Rename", 22)
        rn.clicked.connect(lambda _=False, tid=tab["id"]: self._rename(tid))
        de = btn_icon("✕", "Delete page", 22)
        de.clicked.connect(lambda _=False, tid=tab["id"]: self._delete(tid))
        rl.addWidget(rn); rl.addWidget(de)
        return row

    def _tab(self, tid):
        for t in self._notes["tabs"]:
            if t["id"] == tid: return t
        return None

    def _select(self, tid):
        self.flush()
        self._cur = tid
        tab = self._tab(tid)
        blocker = self._editor.blockSignals(True)
        self._editor.setHtml(tab.get("html", "") if tab else "")
        self._editor.blockSignals(blocker)
        self._render_pages()

    def _add_page(self):
        dlg = TextPromptDialog(self.window(), "New page", "Page name", "New page")
        if dlg.exec_() == QDialog.Accepted and dlg.value():
            t = {"id": str(uuid.uuid4()), "name": dlg.value(), "html": ""}
            self._notes["tabs"].append(t)
            save_notes(self._notes)
            self._select(t["id"])

    def _rename(self, tid):
        tab = self._tab(tid)
        if not tab: return
        dlg = TextPromptDialog(self.window(), "Rename page", "Page name", tab["name"])
        if dlg.exec_() == QDialog.Accepted and dlg.value():
            tab["name"] = dlg.value()
            save_notes(self._notes)
            self._render_pages()

    def _delete(self, tid):
        tab = self._tab(tid)
        if not tab: return
        plain = re.sub(r"<[^>]+>", "", tab.get("html", "")).strip()
        if plain or "img" in tab.get("html", ""):
            if ConfirmDialog(self.window(), f"Delete page “{tab['name']}” and its content?""").exec_() != QDialog.Accepted:
                return
        self._notes["tabs"] = [t for t in self._notes["tabs"] if t["id"] != tid]
        if not self._notes["tabs"]:
            self._notes["tabs"] = [{"id": str(uuid.uuid4()), "name": "Notes", "html": ""}]
        save_notes(self._notes)
        if self._cur == tid:
            self._cur = None
            self._select(self._notes["tabs"][0]["id"])
        else:
            self._render_pages()

    # ── persistence ──────────────────────────────────────────────────────────
    def flush(self):
        """Write the current page immediately (called on timer, page switch, close)."""
        if not self._cur:
            return
        tab = self._tab(self._cur)
        if tab is not None:
            html = self._editor.toHtml()
            if html != tab.get("html"):
                tab["html"] = html
                save_notes(self._notes)

    # ── formatting ───────────────────────────────────────────────────────────
    def _merge(self, fmt):
        c = self._editor.textCursor()
        c.mergeCharFormat(fmt)
        self._editor.setTextCursor(c)

    def _heading(self, pt):
        f = QTextCharFormat(); f.setFontPointSize(pt); f.setFontWeight(QFont.Bold)
        self._merge(f)

    def _bold(self):
        cur = self._editor.textCursor().charFormat().fontWeight()
        f = QTextCharFormat()
        f.setFontWeight(QFont.Normal if cur == QFont.Bold else QFont.Bold)
        self._merge(f)

    def _italic(self):
        f = QTextCharFormat()
        f.setFontItalic(not self._editor.textCursor().charFormat().fontItalic())
        self._merge(f)

    def _underline(self):
        f = QTextCharFormat()
        f.setFontUnderline(not self._editor.textCursor().charFormat().fontUnderline())
        self._merge(f)

    def _bullet(self):
        self._editor.textCursor().insertList(QTextListFormat.ListDisc)

    def _table(self):
        dlg = TableDialog(self.window())
        if dlg.exec_() == QDialog.Accepted:
            r, c = dlg.dims()
            self._editor.insert_ref_table(r, c)

    def _normal(self):
        f = QTextCharFormat()
        f.setFontPointSize(10); f.setFontWeight(QFont.Normal)
        f.setFontItalic(False); f.setFontUnderline(False)
        self._merge(f)

    def _image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert image", "", "Images (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not path: return
        data = base64.b64encode(Path(path).read_bytes()).decode()
        ext = Path(path).suffix.lstrip(".").lower()
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        self._editor.insertHtml(
            f'<img src="data:image/{mime};base64,{data}" width="420"><br>')

# ══════════════════════════════════════════════════════════════════════════════
# Auto-update — check GitHub releases, download, swap the exe via helper .bat
# ══════════════════════════════════════════════════════════════════════════════
def _ver_tuple(s):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


class UpdateCheckThread(QThread):
    found = pyqtSignal(str, str)      # version string, download url
    fail  = pyqtSignal(str)

    def run(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "TileDo"})
            with urllib.request.urlopen(req, timeout=12) as r:
                j = json.load(r)
            ver = j.get("name", "") or j.get("tag_name", "")
            dl = ""
            for a in j.get("assets", []):
                if a.get("name") == "TileDo.exe":
                    dl = a.get("browser_download_url", ""); break
            if not dl:
                self.fail.emit("No exe asset found in the latest release."); return
            self.found.emit(ver, dl)
        except Exception as ex:
            self.fail.emit(f"Check failed: {ex}")


class DownloadThread(QThread):
    progress = pyqtSignal(int)        # 0-100, or -1 for unknown size
    done     = pyqtSignal(str)
    fail     = pyqtSignal(str)

    def __init__(self, url, dest):
        super().__init__()
        self._url, self._dest = url, dest

    def run(self):
        try:
            req = urllib.request.Request(self._url, headers={"User-Agent": "TileDo"})
            with urllib.request.urlopen(req, timeout=30) as r, open(self._dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk: break
                    f.write(chunk); got += len(chunk)
                    self.progress.emit(int(got * 100 / total) if total else -1)
            self.done.emit(str(self._dest))
        except Exception as ex:
            self.fail.emit(f"Download failed: {ex}")


def apply_update_and_restart(new_exe: str):
    """Write a helper .bat that waits for this process to exit, swaps the exe,
    relaunches it, then deletes itself."""
    cur = Path(sys.executable)
    bat = DATA_DIR / "tiledo_update.bat"
    bat.write_text(
        "@echo off\r\n"
        f"set PID={os.getpid()}\r\n"
        ":wait\r\n"
        "tasklist /FI \"PID eq %PID%\" 2>nul | findstr /r \"\\<%PID%\\>\" >nul\r\n"
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        "set /a tries=0\r\n"
        ":try\r\n"
        f"move /y \"{new_exe}\" \"{cur}\" >nul 2>&1\r\n"
        "if errorlevel 1 (\r\n"
        "  set /a tries+=1\r\n"
        "  if %tries% lss 15 ( timeout /t 1 /nobreak >nul & goto try )\r\n"
        ")\r\n"
        f"start \"\" \"{cur}\"\r\n"
        "del \"%~f0\"\r\n",
        encoding="ascii")
    CREATE_NO_WINDOW, DETACHED = 0x08000000, 0x00000008
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=CREATE_NO_WINDOW | DETACHED,
                     close_fds=True)

# ══════════════════════════════════════════════════════════════════════════════
# Settings
# ══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(BaseDialog):
    def __init__(self, parent, data, cfg, app):
        super().__init__(parent, "Settings", 540, 660)
        self._data, self._cfg, self._app = data, cfg, app
        self._stage_rows = []          # (id-or-None, name_edit, colour_cell, deleted_flag)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget(); inner.setStyleSheet("background: transparent;")
        self._iv = QVBoxLayout(inner)
        self._iv.setContentsMargins(2, 2, 8, 2); self._iv.setSpacing(9)
        sc.setWidget(inner)
        self.add(sc)
        self._build(self._iv)
        row = QHBoxLayout()
        ok = btn_primary("Save"); ok.clicked.connect(self._save)
        no = btn_quiet("Cancel"); no.clicked.connect(self.reject)
        row.addStretch(); row.addWidget(no); row.addWidget(ok)
        self.add_lay(row)
        ver = QLabel(f"TileDo v{APP_VERSION}")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet(f"color: {FAINT}; font-size: 8pt; background: transparent;")
        self.add(ver)

    def _swatch(self, holder):
        b = QPushButton(); b.setFixedSize(34, 24)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"background: {holder[0]}; border-radius: 5px; border: 1px solid {BDR_H};")

        def pick(_=False):
            c = QColorDialog.getColor(QColor(holder[0]), self)
            if c.isValid():
                holder[0] = c.name()
                b.setStyleSheet(f"background: {c.name()}; border-radius: 5px; border: 1px solid {BDR_H};")
        b.clicked.connect(pick)
        return b

    def _build(self, v):
        v.addWidget(micro_label("Grid"))
        gr = QHBoxLayout()
        gr.addWidget(QLabel("Card width (px):"))
        self._ts = QSpinBox(); self._ts.setRange(150, 420)
        self._ts.setValue(self._cfg.get("tile_size", 230)); self._ts.setFixedWidth(76)
        gr.addWidget(self._ts); gr.addStretch()
        v.addLayout(gr)

        v.addWidget(sep_line())
        v.addWidget(micro_label("Behaviour"))
        self._tray_ck = QCheckBox("Close button hides to the system tray")
        self._tray_ck.setChecked(self._cfg.get("close_to_tray", True))
        v.addWidget(self._tray_ck)
        self._startup_ck = QCheckBox("Start with Windows (opens in tray)")
        self._startup_ck.setChecked(get_startup_enabled())
        v.addWidget(self._startup_ck)
        hk_text = "Global quick-capture hotkey  (Ctrl+Alt+T)"
        if not getattr(self._app, "hotkey_ok", True):
            hk_text += "  — unavailable, another app owns it"
        self._hk_ck = QCheckBox(hk_text)
        self._hk_ck.setChecked(self._cfg.get("hotkey_enabled", True))
        v.addWidget(self._hk_ck)

        v.addWidget(sep_line())
        v.addWidget(micro_label("Templates"))
        self._tpl_rows = []
        if self._data.get("templates"):
            for tp in self._data["templates"]:
                r = QWidget(); rl = QHBoxLayout(r)
                rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
                lab = QLabel(f"{tp['name']}  ·  {count_template_items(tp.get('items', []))} items")
                lab.setStyleSheet("background: transparent;")
                rl.addWidget(lab, 1)
                de = btn_icon("✕", "Delete template", 24)
                entry = {"id": tp["id"], "row": r, "deleted": False}

                def kill(_=False, en=entry):
                    en["deleted"] = True
                    en["row"].hide()
                de.clicked.connect(kill)
                rl.addWidget(de)
                v.addWidget(r)
                self._tpl_rows.append(entry)
        else:
            hint = QLabel("None yet — use “Save as template…” on a task card.")
            hint.setStyleSheet(f"color: {FAINT}; font-size: 8pt;")
            v.addWidget(hint)

        v.addWidget(sep_line())
        v.addWidget(micro_label("Priority colours"))
        self._prio_holders = {}
        for p in ("high", "medium", "low"):
            holder = [PRIO_COLOR[p]]
            self._prio_holders[p] = holder
            r = QHBoxLayout()
            lab = QLabel(PRIO_LABEL[p]); lab.setFixedWidth(70)
            r.addWidget(lab); r.addWidget(self._swatch(holder)); r.addStretch()
            v.addLayout(r)

        v.addWidget(sep_line())
        v.addWidget(micro_label("Progress stages"))
        self._stage_box = QVBoxLayout(); self._stage_box.setSpacing(5)
        v.addLayout(self._stage_box)
        for s in self._data.get("stages", []):
            self._stage_row(s["id"], s["name"], s["color"])
        add_s = btn_quiet("＋ Add stage")
        add_s.clicked.connect(lambda _=False: self._stage_row(None, "New stage", "#7a8088"))
        v.addWidget(add_s)

        v.addWidget(sep_line())
        v.addWidget(micro_label("Updates"))
        ur = QHBoxLayout()
        self._upd_status = QLabel(f"Current version: v{APP_VERSION}")
        self._upd_status.setStyleSheet(f"color: {DIM}; background: transparent;")
        ur.addWidget(self._upd_status, 1)
        self._chk_btn = btn_quiet("Check for updates")
        self._chk_btn.clicked.connect(self._check_updates)
        ur.addWidget(self._chk_btn)
        v.addLayout(ur)
        self._auto_ck = QCheckBox("Check automatically on startup")
        self._auto_ck.setChecked(self._cfg.get("auto_update", True))
        v.addWidget(self._auto_ck)
        self._dl_bar = QProgressBar(); self._dl_bar.setRange(0, 100); self._dl_bar.hide()
        v.addWidget(self._dl_bar)
        self._install_btn = btn_primary("Download && install")
        self._install_btn.hide()
        self._install_btn.clicked.connect(self._install)
        v.addWidget(self._install_btn)
        self._found_url = None
        if self._app.pending_update:
            ver, url = self._app.pending_update
            self._offer(ver, url)

        v.addWidget(sep_line())
        v.addWidget(micro_label("Data"))
        dr = QHBoxLayout()
        p = QLabel(str(DATA_DIR)); p.setStyleSheet(f"color: {FAINT}; font-size: 8pt;")
        dr.addWidget(p, 1)
        op = btn_quiet("Open folder")
        op.clicked.connect(lambda _=False: os.startfile(str(DATA_DIR)))
        dr.addWidget(op)
        v.addLayout(dr)
        v.addStretch()

    def _stage_row(self, sid, name, color):
        row = QWidget(); rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
        ne = QLineEdit(name); ne.setFixedWidth(190)
        holder = [color]
        sw = self._swatch(holder)
        de = btn_icon("✕", "Remove stage", 24)
        entry = {"id": sid, "name_edit": ne, "color": holder, "row": row, "deleted": False}

        def remove(_=False):
            live = [e for e in self._stage_rows if not e["deleted"]]
            if len(live) <= 1:
                return                      # keep at least one stage
            entry["deleted"] = True
            row.hide()
        de.clicked.connect(remove)
        rl.addWidget(ne); rl.addWidget(sw); rl.addWidget(de); rl.addStretch()
        self._stage_box.addWidget(row)
        self._stage_rows.append(entry)

    # ── updates ──────────────────────────────────────────────────────────────
    def _check_updates(self):
        self._chk_btn.setEnabled(False)
        self._upd_status.setText("Checking…")
        self._checker = UpdateCheckThread()
        self._checker.found.connect(self._on_found)
        self._checker.fail.connect(self._on_fail)
        self._checker.start()

    def _on_found(self, ver, url):
        self._chk_btn.setEnabled(True)
        if _ver_tuple(ver) > _ver_tuple(APP_VERSION):
            self._offer(ver, url)
        else:
            self._upd_status.setText(f"Up to date ✓  (v{APP_VERSION})")

    def _offer(self, ver, url):
        self._found_url = url
        self._app.pending_update = (ver, url)
        self._upd_status.setText(f"Update available: {ver}")
        self._upd_status.setStyleSheet(f"color: {ACC}; background: transparent;")
        if getattr(sys, "frozen", False):
            self._install_btn.show()
        else:
            self._upd_status.setText(
                f"Update available: {ver} — running from source, use git pull")

    def _on_fail(self, msg):
        self._chk_btn.setEnabled(True)
        self._upd_status.setText(msg)

    def _install(self):
        if not self._found_url: return
        self._install_btn.setEnabled(False)
        self._dl_bar.show(); self._dl_bar.setValue(0)
        dest = DATA_DIR / "TileDo_new.exe"
        self._dl = DownloadThread(self._found_url, dest)
        self._dl.progress.connect(
            lambda p: self._dl_bar.setValue(p if p >= 0 else 50))
        self._dl.fail.connect(self._on_fail)
        self._dl.done.connect(self._on_downloaded)
        self._dl.start()

    def _on_downloaded(self, path):
        self._upd_status.setText("Restarting to apply update…")
        apply_update_and_restart(path)
        self.accept()
        self._app.really_quit()

    # ── save ─────────────────────────────────────────────────────────────────
    def _save(self):
        self._cfg["tile_size"] = self._ts.value()
        self._cfg["auto_update"] = self._auto_ck.isChecked()
        self._cfg["close_to_tray"] = self._tray_ck.isChecked()
        self._cfg["hotkey_enabled"] = self._hk_ck.isChecked()
        set_startup(self._startup_ck.isChecked())
        removed_tpl = {e["id"] for e in self._tpl_rows if e["deleted"]}
        if removed_tpl:
            self._data["templates"] = [t for t in self._data["templates"]
                                       if t["id"] not in removed_tpl]
        for p, holder in self._prio_holders.items():
            PRIO_COLOR[p] = holder[0]

        kept, removed_ids = [], set()
        for e in self._stage_rows:
            if e["deleted"]:
                if e["id"]: removed_ids.add(e["id"])
                continue
            name = e["name_edit"].text().strip() or "Stage"
            kept.append({"id": e["id"] or str(uuid.uuid4()),
                         "name": name, "color": e["color"][0]})
        if not kept:
            kept = [dict(s) for s in DEFAULT_STAGES]
        self._data["stages"] = kept
        # remap tasks whose stage was deleted so they never show a raw id
        valid = {s["id"] for s in kept}
        fallback = kept[0]["id"]
        for t in self._data["tasks"]:
            if t.get("stage") not in valid:
                t["stage"] = fallback

        save_data(self._data)
        save_cfg(self._cfg)
        self._app.apply_hotkey()
        self._app.refresh()
        self.accept()

# ══════════════════════════════════════════════════════════════════════════════
# Global hotkey (Ctrl+Alt+T) + quick-capture popup
# ══════════════════════════════════════════════════════════════════════════════
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xA117

class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, cb):
        super().__init__()
        self._cb = cb

    def nativeEventFilter(self, etype, message):
        if etype in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._cb()
                return True, 0
        return False, 0


class QuickCaptureDialog(QDialog):
    def __init__(self, app):
        super().__init__(None)
        self._app = app
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(440, 120)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        frame = QFrame(); frame.setObjectName("qc")
        frame.setStyleSheet(
            f"#qc {{ background: {BG}; border: 1px solid {ACC}; border-radius: 10px; }}")
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(26); sh.setColor(QColor(0, 0, 0, 200)); sh.setOffset(0, 4)
        frame.setGraphicsEffect(sh)
        outer.addWidget(frame)
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 10, 14, 10); v.setSpacing(6)
        v.addWidget(micro_label("Quick capture", ACC))
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("New task…")
        ef = self._edit.font(); ef.setPointSize(11); self._edit.setFont(ef)
        self._edit.returnPressed.connect(self._add)
        v.addWidget(self._edit)
        hint = QLabel("Enter to add — keep typing to add more · Esc to close")
        hint.setStyleSheet(f"color: {FAINT}; font-size: 8pt;")
        v.addWidget(hint)
        s = QApplication.primaryScreen().availableGeometry()
        self.move(s.center().x() - self.width() // 2,
                  s.top() + int(s.height() * 0.26))

    def _add(self):
        title = self._edit.text().strip()
        if not title:
            self.close(); return
        self._app.snapshot()
        t = mk_task(title, "medium", None)
        b = bucket(self._app.data, None, "medium")
        t["order"] = max((x.get("order", 0) for x in b), default=-10) + 10
        self._app.data["tasks"].append(t)
        save_data(self._app.data)
        self._app.refresh()
        self._edit.clear()
        self._edit.setPlaceholderText("Added ✓  — next task…")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data = load_data()
        self.cfg = load_cfg()
        self.notes = load_notes()
        self.pending_update = None
        self._parent_id = None
        self._children = []           # tracked non-modal windows
        self._undo_stack = []
        self._quitting = False
        self._tray = None
        self._tray_notified = False
        self._qc = None
        self.hotkey_ok = True

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(480, 360)
        self._restore_geometry()
        self._build()
        self._init_tray()
        self.apply_hotkey()
        self.update_meta()
        if self.cfg.get("auto_update", True):
            QTimer.singleShot(4000, self._auto_check)

    # ── undo ─────────────────────────────────────────────────────────────────
    def snapshot(self, include_archive=False):
        """Push a restore point before a mutating operation (Ctrl+Z pops it)."""
        entry = {"tasks": copy.deepcopy(self.data["tasks"])}
        if include_archive:
            entry["archive"] = copy.deepcopy(load_archive())
        self._undo_stack.append(entry)
        del self._undo_stack[:-30]

    def _undo(self):
        fw = QApplication.focusWidget()
        if isinstance(fw, (QTextEdit, QLineEdit)):
            fw.undo()               # text fields keep their native undo
            return
        if not self._undo_stack:
            return
        entry = self._undo_stack.pop()
        self.data["tasks"] = entry["tasks"]
        save_data(self.data)
        if entry.get("archive") is not None:
            save_archive(entry["archive"])
        self.refresh()

    # ── tray / hotkey ────────────────────────────────────────────────────────
    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(make_app_icon(), self)
        self._tray_menu = QMenu()
        self._tray_menu.addAction("Open TileDo").triggered.connect(self.show_from_tray)
        self._tray_menu.addAction("Quick capture\tCtrl+Alt+T").triggered.connect(
            self.show_quick_capture)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction("Quit").triggered.connect(self.really_quit)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.setToolTip("TileDo")
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_from_tray()

    def show_from_tray(self):
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_quick_capture(self):
        if self._qc is not None and self._qc.isVisible():
            self._qc.raise_(); self._qc.activateWindow()
            self._qc._edit.setFocus()
            return
        self._qc = QuickCaptureDialog(self)
        self._qc.show(); self._qc.raise_(); self._qc.activateWindow()
        self._qc._edit.setFocus()

    def apply_hotkey(self):
        self._unregister_hotkey()
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        if not self.cfg.get("hotkey_enabled", True):
            return
        try:
            MOD_ALT, MOD_CONTROL = 0x1, 0x2
            ok = ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, MOD_ALT | MOD_CONTROL, ord("T"))
            self.hotkey_ok = bool(ok)
            if ok and not getattr(self, "_hk_filter", None):
                self._hk_filter = HotkeyFilter(self.show_quick_capture)
                QApplication.instance().installNativeEventFilter(self._hk_filter)
        except Exception:
            self.hotkey_ok = False

    def _unregister_hotkey(self):
        try:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:
            pass

    def really_quit(self):
        self._quitting = True
        self.close()
        QApplication.quit()

    # ── geometry ─────────────────────────────────────────────────────────────
    def _restore_geometry(self):
        r = QRect(self.cfg.get("x", 100), self.cfg.get("y", 60),
                  self.cfg.get("w", 1000), self.cfg.get("h", 720))
        visible = False
        for s in QApplication.screens():
            if s.availableGeometry().intersected(r).width() > 60:
                visible = True; break
        if not visible:
            s = QApplication.primaryScreen().availableGeometry()
            r.moveCenter(s.center())
        self.setGeometry(r)

    # ── chrome ───────────────────────────────────────────────────────────────
    def _build(self):
        central = QWidget(); central.setStyleSheet("background: transparent;")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)

        frame = QFrame(); frame.setObjectName("root")
        frame.setStyleSheet(
            f"#root {{ background: {BG}; border: 1px solid {BDR_H}; border-radius: 10px; }}")
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(34); sh.setColor(QColor(0, 0, 0, 200)); sh.setOffset(0, 5)
        frame.setGraphicsEffect(sh)
        outer.addWidget(frame)
        fl = QVBoxLayout(frame); fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(0)

        # titlebar with search
        self.bar = DragBar("TileDo", self, 42)
        self.bar.setStyleSheet(
            f"DragBar {{ background: {NAV}; border-top-left-radius: 10px; "
            f"border-top-right-radius: 10px; border-bottom: 1px solid {BDR}; }}")
        self._searchbox = QLineEdit()
        self._searchbox.setPlaceholderText("Search…  (Ctrl+F)")
        self._searchbox.setFixedWidth(200)
        self._searchbox.setStyleSheet(
            f"QLineEdit {{ background: {BG}; border: 1px solid {BDR}; border-radius: 6px; "
            f"padding: 4px 9px; color: {TEXT}; font-size: 8.5pt; }}"
            f"QLineEdit:focus {{ border-color: {ACC}; }}")
        self._searchbox.textChanged.connect(self._on_search)
        self.bar.center_slot.insertWidget(3, self._searchbox)
        fl.addWidget(self.bar)

        # nav row: tabs + actions
        nav = QFrame()
        nav.setStyleSheet(f"QFrame {{ background: {NAV}; border-bottom: 1px solid {BDR}; }}")
        nl = QHBoxLayout(nav); nl.setContentsMargins(10, 0, 10, 0); nl.setSpacing(2)
        self._tabs = {}
        for key, label in (("tasks", "Tasks"), ("recurring", "Recurring"), ("notes", "Notes")):
            b = QPushButton(label)
            b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {DIM}; border: none; "
                f"border-bottom: 2px solid transparent; border-radius: 0; "
                f"padding: 11px 13px; font-weight: 600; }}"
                f"QPushButton:hover {{ color: {TEXT}; }}"
                f"QPushButton:checked {{ color: {ACC}; border-bottom-color: {ACC}; }}")
            b.clicked.connect(lambda _=False, k=key: self.switch_tab(k))
            nl.addWidget(b)
            self._tabs[key] = b
        nl.addStretch()
        add = btn_primary("＋ Add")
        add.clicked.connect(self._add_clicked)
        nl.addWidget(add)
        allb = btn_quiet("All tasks")
        allb.clicked.connect(self._open_all)
        nl.addWidget(allb)
        self._gear = btn_icon("⚙", "Settings", 30)
        self._gear.clicked.connect(self._open_settings)
        nl.addWidget(self._gear)
        fl.addWidget(nav)

        # tasks page (breadcrumb + quick add + grid)
        tasks_page = QWidget(); tasks_page.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(tasks_page)
        tv.setContentsMargins(12, 8, 12, 6); tv.setSpacing(7)
        self._crumb = Breadcrumb()
        self._crumb.navigate.connect(self.navigate)
        self._crumb.move_to.connect(self._move_to_ancestor)
        tv.addWidget(self._crumb)
        self._quick = QLineEdit()
        self._quick.setPlaceholderText("＋  Quick add…  (Enter)")
        self._quick.returnPressed.connect(self._quick_add)
        tv.addWidget(self._quick)
        self._grid = CardGrid(self, self.data, self.cfg, mode="focus", parent_id=None)
        tv.addWidget(self._grid, 1)
        self._done_strip = QWidget(); self._done_strip.setStyleSheet("background: transparent;")
        self._done_v = QVBoxLayout(self._done_strip)
        self._done_v.setContentsMargins(0, 0, 0, 0); self._done_v.setSpacing(3)
        tv.addWidget(self._done_strip)

        # recurring page
        rec_page = QWidget(); rec_page.setStyleSheet("background: transparent;")
        rv = QVBoxLayout(rec_page)
        rv.setContentsMargins(12, 10, 12, 6); rv.setSpacing(7)
        self._rquick = QLineEdit()
        self._rquick.setPlaceholderText("＋  Add recurring task…  (Enter)")
        self._rquick.returnPressed.connect(self._quick_add_rec)
        rv.addWidget(self._rquick)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_all = btn_quiet("↺ Reset all done")
        reset_all.clicked.connect(self._reset_recurring)
        reset_row.addWidget(reset_all)
        rv.addLayout(reset_row)
        self._rec_grid = CardGrid(self, self.data, self.cfg, mode="flow", recurring=True)
        rv.addWidget(self._rec_grid, 1)

        self._notes_view = NotesView(self.notes, self)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(tasks_page)
        self._stack.addWidget(rec_page)
        self._stack.addWidget(self._notes_view)
        fl.addWidget(self._stack, 1)

        grip_row = QHBoxLayout(); grip_row.setContentsMargins(0, 0, 3, 3)
        grip_row.addStretch()
        grip = QSizeGrip(frame); grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip)
        fl.addLayout(grip_row)

        QShortcut(QKeySequence("Ctrl+F"), self,
                  activated=lambda: (self._searchbox.setFocus(), self._searchbox.selectAll()))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._add_clicked)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Escape"), self, activated=self._escape)

        self.switch_tab("tasks")
        self._crumb.set_path(self.data, None)

    # ── navigation ───────────────────────────────────────────────────────────
    def switch_tab(self, key):
        idx = {"tasks": 0, "recurring": 1, "notes": 2}[key]
        if self._stack.currentIndex() == 2:
            self._notes_view.flush()
        self._stack.setCurrentIndex(idx)
        for k, b in self._tabs.items():
            b.setChecked(k == key)
        if key == "recurring":
            self._rec_grid.rebuild()
        elif key == "tasks":
            self._grid.rebuild()

    def navigate(self, parent_id):
        # guard against navigating into a deleted task
        if parent_id is not None and task_by_id(self.data, parent_id) is None:
            parent_id = None
        self._parent_id = parent_id
        self._grid.parent_id = parent_id
        self._grid.mode = "focus" if parent_id is None else "flow"
        self._grid.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if parent_id is None else Qt.ScrollBarAsNeeded)
        self._crumb.set_path(self.data, parent_id)
        self._quick.setPlaceholderText(
            "＋  Quick add…  (Enter)" if parent_id is None
            else "＋  Add item here…  (Enter)")
        self._grid.rebuild()
        self._render_done_strip()

    def open_task(self, task):
        if self._searchbox.text().strip():
            self._searchbox.clear()
        self.navigate(task["id"])

    def _escape(self):
        if self._searchbox.text():
            self._searchbox.clear(); return
        if self._parent_id is not None:
            t = task_by_id(self.data, self._parent_id)
            self.navigate(t.get("parent_id") if t else None)

    def _move_to_ancestor(self, src_id, parent_id):
        src = task_by_id(self.data, src_id)
        if not src: return
        if parent_id is not None and (parent_id == src_id
                or parent_id in descendant_ids(self.data, src_id)):
            return
        self.snapshot()
        src["parent_id"] = parent_id
        b = bucket(self.data, parent_id, src["priority"])
        if src not in b: b.append(src)
        renumber(b)
        save_data(self.data)
        self.refresh()

    # ── drag & drop model ops ─────────────────────────────────────────────────
    def handle_drop(self, src_id, target_id, mode):
        src = task_by_id(self.data, src_id)
        tgt = task_by_id(self.data, target_id)
        if not src or not tgt or src_id == target_id:
            return
        if target_id in descendant_ids(self.data, src_id):
            return
        self.snapshot()
        if mode == "nest":
            nest_under(self.data, src, tgt)
        else:
            insert_relative(self.data, src, tgt, mode)
        save_data(self.data)
        self.refresh()

    def handle_priority_drop(self, src_id, priority):
        src = task_by_id(self.data, src_id)
        if not src: return
        self.snapshot()
        src["priority"] = priority
        src["parent_id"] = self._parent_id
        b = bucket(self.data, self._parent_id, priority)
        if src not in b: b.append(src)
        renumber(b)
        save_data(self.data)
        self.refresh()

    # ── quick add / actions ──────────────────────────────────────────────────
    def _quick_add(self):
        title = self._quick.text().strip()
        if not title: return
        self.snapshot()
        t = mk_task(title, "medium", self._parent_id)
        b = bucket(self.data, self._parent_id, "medium")
        t["order"] = (max((x.get("order", 0) for x in b), default=-10)) + 10
        self.data["tasks"].append(t)
        save_data(self.data)
        self._quick.clear()
        self.refresh()

    def _quick_add_rec(self):
        title = self._rquick.text().strip()
        if not title: return
        self.snapshot()
        t = mk_task(title, "medium", None, recurring=True)
        b = bucket(self.data, None, "medium", recurring=True)
        t["order"] = (max((x.get("order", 0) for x in b), default=-10)) + 10
        self.data["tasks"].append(t)
        save_data(self.data)
        self._rquick.clear()
        self.refresh()

    def _reset_recurring(self):
        changed = any(t.get("recurring") and t.get("completed")
                      for t in self.data["tasks"])
        if not changed:
            return
        self.snapshot()
        for t in self.data["tasks"]:
            if t.get("recurring") and t.get("completed"):
                t["completed"] = False
        save_data(self.data)
        self.refresh()

    def _add_clicked(self):
        if self._stack.currentIndex() == 1:
            AddTaskDialog(self, self.data, self, recurring=True).exec_()
        else:
            AddTaskDialog(self, self.data, self, parent_id=self._parent_id).exec_()

    def _open_all(self):
        dlg = AllTasksDialog(self, self.data, self)
        self._track(dlg)

    def open_task_window(self, task):
        w = TaskWindow(self, task, self.data, self.cfg, self)
        self._track(w)

    def _track(self, dlg):
        self._children.append(dlg)
        dlg.show(); dlg.raise_(); dlg.activateWindow()

    def _open_settings(self):
        SettingsDialog(self, self.data, self.cfg, self).exec_()
        self._gear.setText("⚙")

    # ── search ───────────────────────────────────────────────────────────────
    def _on_search(self, text):
        if self._stack.currentIndex() == 2:
            self._notes_view._search.setText(text)
            return
        q = text.strip().lower()
        if not q:
            self._grid.rebuild()
            return
        self._render_search(q)

    def _render_search(self, q):
        g = self._grid
        for w, _ in g._items:
            w.deleteLater()
        g._items = []
        if g._queued_chip:
            g._queued_chip.deleteLater(); g._queued_chip = None
        matches = [t for t in self.data["tasks"]
                   if not t.get("recurring") and not t.get("completed")
                   and (q in t["title"].lower() or q in (t.get("notes") or "").lower())]
        matches.sort(key=lambda t: (PRIO_ORDER.get(t["priority"], 1), t.get("order", 0)))
        g._add_header(None, f"Search · {len(matches)} match{'es' if len(matches) != 1 else ''}")
        for t in matches[:60]:
            g._add_card(t)
        if not matches:
            g._add_empty(f"No open tasks match “{q}”.")
        g._relayout()

    # ── done strip (completed children in drilled view) ──────────────────────
    def _render_done_strip(self):
        while self._done_v.count():
            it = self._done_v.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        if self._parent_id is None:
            return
        done = [t for t in children_of(self.data, self._parent_id) if t.get("completed")]
        if not done:
            return
        self._done_v.addWidget(micro_label(f"Completed · {len(done)}"))
        for t in done[:8]:
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background: {SURF2}; border: none; border-radius: 5px; }}")
            rl = QHBoxLayout(row); rl.setContentsMargins(7, 2, 7, 2); rl.setSpacing(7)
            ck = QCheckBox(); ck.setChecked(True)

            def untick(state, task=t):
                if not state:
                    self.snapshot()
                    task["completed"] = False
                    save_data(self.data)
                    self.refresh()
            ck.stateChanged.connect(untick)
            rl.addWidget(ck)
            lab = QLabel(t["title"])
            lab.setStyleSheet(f"color: {FAINT}; text-decoration: line-through; background: transparent;")
            rl.addWidget(lab, 1)
            self._done_v.addWidget(row)
        if len(done) > 8:
            more = QLabel(f"  +{len(done) - 8} more in All tasks")
            more.setStyleSheet(f"color: {FAINT}; font-size: 8pt;")
            self._done_v.addWidget(more)

    # ── refresh fan-out ──────────────────────────────────────────────────────
    def refresh(self):
        if self._parent_id is not None and task_by_id(self.data, self._parent_id) is None:
            self.navigate(None)
            self.update_meta()
            return
        if self._searchbox.text().strip() and self._stack.currentIndex() == 0:
            self._render_search(self._searchbox.text().strip().lower())
        else:
            self._grid.rebuild()
        if self._stack.currentIndex() == 1:
            self._rec_grid.rebuild()
        self._crumb.set_path(self.data, self._parent_id)
        self._render_done_strip()
        self.update_meta()
        for w in list(self._children):
            if not w.isVisible():
                self._children.remove(w)
            elif hasattr(w, "_render"):
                w._render()

    def update_meta(self):
        self.bar.set_meta(f"{top_pending_count(self.data)} open")

    # ── updates ──────────────────────────────────────────────────────────────
    def _auto_check(self):
        self._auto_thread = UpdateCheckThread()

        def on_found(ver, url):
            if _ver_tuple(ver) > _ver_tuple(APP_VERSION):
                self.pending_update = (ver, url)
                self._gear.setText("⚙•")
                self._gear.setToolTip(f"Update available: {ver} — open Settings")
        self._auto_thread.found.connect(on_found)
        self._auto_thread.fail.connect(lambda m: None)
        self._auto_thread.start()

    # ── shutdown ─────────────────────────────────────────────────────────────
    def closeEvent(self, e):
        self._notes_view.flush()
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.cfg.update({"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()})
        save_cfg(self.cfg)
        if (self._tray is not None and self.cfg.get("close_to_tray", True)
                and not self._quitting):
            e.ignore()
            self.hide()
            if not self._tray_notified:
                self._tray.showMessage(
                    "TileDo", "Still running here — click to reopen.",
                    QSystemTrayIcon.Information, 2500)
                self._tray_notified = True
            return
        for w in self._children:
            try: w.close()
            except Exception: pass
        self._unregister_hotkey()
        if self._tray is not None:
            self._tray.hide()
        e.accept()
        QApplication.quit()

# ══════════════════════════════════════════════════════════════════════════════
def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("TileDo")
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(SS)

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Base, QColor(SURF2))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor("#272b2f"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACC))
    pal.setColor(QPalette.HighlightedText, QColor("#141414"))
    app.setPalette(pal)

    app.setWindowIcon(make_app_icon())
    app.setQuitOnLastWindowClosed(False)   # tray keeps us alive; quit is explicit

    # Single instance: if TileDo is already running, tell it to show itself and exit.
    IPC = "tiledo-ipc"
    probe = QLocalSocket()
    probe.connectToServer(IPC)
    if probe.waitForConnected(400):
        probe.write(b"show"); probe.flush()
        probe.waitForBytesWritten(400)
        probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(IPC)         # clear stale socket after a crash

    win = MainWindow()

    server = QLocalServer()
    server.listen(IPC)

    def _on_ipc():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: (c.readAll(), win.show_from_tray()))
            conn.disconnected.connect(conn.deleteLater)
    server.newConnection.connect(_on_ipc)

    if "--tray" in sys.argv and win._tray is not None:
        pass                                # start hidden in the tray
    else:
        win.show()
    rc = app.exec_()
    server.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
