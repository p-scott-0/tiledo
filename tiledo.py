#!/usr/bin/env python3
"""TileDo — PyQt5 frameless tile-based to-do"""

APP_VERSION = "1.1.0"

import sys, json, uuid, base64
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QDialog, QLabel,
    QPushButton, QToolButton, QMenu, QLineEdit, QTextEdit, QComboBox,
    QScrollArea, QSizeGrip, QRadioButton, QCheckBox, QSpinBox,
    QButtonGroup, QColorDialog, QMessageBox, QGraphicsDropShadowEffect,
    QFileDialog, QStackedWidget, QInputDialog, QLayout,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
)
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QEvent, QSize
from PyQt5.QtGui import QColor, QPixmap, QTextCursor, QTextCharFormat, QTextBlockFormat, QFont, QTextListFormat

DATA_DIR  = Path.home() / ".tiledo"
DATA_FILE = DATA_DIR / "data.json"
CFG_FILE  = DATA_DIR / "settings.json"

BG = "#0d0d1a"; BG2 = "#12121f"; BG3 = "#18182c"
BDR = "#252542"; BDR_H = "#38385a"
TEXT = "#ddddf8"; DIM = "#72729a"; ACCENT = "#6c63ff"
DONE_CLR = "#3ecfc6"; BTN = "#1e1e38"; BTN_H = "#28284a"

TILE_BG  = {"high": "#9c1a32", "medium": "#7a5800", "low": "#1a3ea8"}
TILE_ACC = {"high": "#ff607a", "medium": "#ffe600", "low": "#4aaaff"}
PL = {"high": "HIGH", "medium": "MED", "low": "LOW"}

DEFAULT_STAGES = [
    {"id": "todo",        "name": "To Do",       "color": "#5a5a80"},
    {"id": "in_progress", "name": "In Progress",  "color": "#4a78ff"},
    {"id": "blocked",     "name": "Blocked",      "color": "#ff4a68"},
    {"id": "review",      "name": "Review",       "color": "#ffaa38"},
]
DEFAULT_CFG = {
    "tile_size": 220, "x": 100, "y": 60, "w": 980, "h": 740,
    "priority_bg":  {"high": "#9c1a32", "medium": "#7a5800", "low": "#1a3ea8"},
    "priority_acc": {"high": "#ff607a", "medium": "#ffe600", "low": "#4aaaff"},
}

SS = f"""
* {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 9pt; color: {TEXT}; outline: 0; }}
QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: {BG2}; width: 5px; border-radius: 3px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BDR_H}; border-radius: 3px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ height: 0; border: none; }}
QLineEdit, QTextEdit {{
    background: {BG3}; border: 1.5px solid {BDR}; border-radius: 8px;
    padding: 7px 11px; color: {TEXT}; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox {{
    background: {BG3}; border: 1.5px solid {BDR}; border-radius: 8px;
    padding: 6px 11px; color: {TEXT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG2}; border: 1px solid {BDR_H}; border-radius: 8px;
    selection-background-color: {BTN_H}; padding: 4px; outline: 0;
}}
QPushButton {{
    background: {BTN}; color: {DIM}; border: none;
    border-radius: 7px; padding: 5px 12px; font-size: 8pt;
}}
QPushButton:hover {{ background: {BTN_H}; color: {TEXT}; }}
QPushButton:pressed {{ background: {BG3}; }}
QRadioButton {{ spacing: 7px; }}
QRadioButton::indicator {{
    width: 14px; height: 14px; border-radius: 7px;
    border: 2px solid {BDR_H}; background: transparent;
}}
QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 2px solid {BDR_H}; background: transparent;
}}
QCheckBox::indicator:checked {{ background: {DONE_CLR}; border-color: {DONE_CLR}; }}
QSpinBox {{
    background: {BG3}; border: 1.5px solid {BDR}; border-radius: 8px;
    padding: 5px 8px; color: {TEXT};
}}
QSpinBox::up-button, QSpinBox::down-button {{ background: {BTN}; border: none; width: 18px; }}
QToolButton {{ background: transparent; border: none; }}
QMenu {{ background: {BG2}; border: 1px solid {BDR_H}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 20px; border-radius: 5px; }}
QMenu::item:selected {{ background: {BTN_H}; }}
"""

# ── Data ───────────────────────────────────────────────────────────────────────
def _empty():
    return {"tasks": [], "stages": list(DEFAULT_STAGES),
            "notes_tabs": [{"id": str(uuid.uuid4()), "name": "Notes", "html": ""}]}

def load():
    DATA_DIR.mkdir(exist_ok=True)
    try:
        d = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else _empty()
        # migrate old single-notes format
        if "notes_html" in d and "notes_tabs" not in d:
            d["notes_tabs"] = [{"id": str(uuid.uuid4()), "name": "Notes", "html": d.pop("notes_html")}]
        d.setdefault("notes_tabs", [{"id": str(uuid.uuid4()), "name": "Notes", "html": ""}])
        return d
    except Exception:
        return _empty()

def save(d): DATA_FILE.write_text(json.dumps(d, indent=2))

def load_cfg():
    try:
        cfg = {**DEFAULT_CFG, **json.loads(CFG_FILE.read_text())} if CFG_FILE.exists() else dict(DEFAULT_CFG)
    except Exception:
        cfg = dict(DEFAULT_CFG)
    # Sync priority colours from cfg into the module-level dicts
    TILE_BG.update(cfg.get("priority_bg",  DEFAULT_CFG["priority_bg"]))
    TILE_ACC.update(cfg.get("priority_acc", DEFAULT_CFG["priority_acc"]))
    return cfg

def save_cfg(c):
    c["priority_bg"]  = dict(TILE_BG)
    c["priority_acc"] = dict(TILE_ACC)
    CFG_FILE.write_text(json.dumps(c, indent=2))

def mk_task(title, priority="medium", parent_id=None, recurring=False):
    return {"id": str(uuid.uuid4()), "title": title, "notes": "",
            "priority": priority, "stage": "todo", "parent_id": parent_id,
            "recurring": recurring, "completed": False, "order": 9999,
            "created": datetime.now().isoformat()}

def stage_color(d, sid):
    for s in d.get("stages", DEFAULT_STAGES):
        if s["id"] == sid: return s["color"]
    return "#5a5a80"

def stage_name(d, sid):
    for s in d.get("stages", DEFAULT_STAGES):
        if s["id"] == sid: return s["name"]
    return sid

def focus_tasks(d, parent_id=None):
    ts = [t for t in d["tasks"] if not t.get("completed") and not t.get("recurring")
          and t.get("parent_id") == parent_id]
    ts.sort(key=lambda t: ({"high":0,"medium":1,"low":2}.get(t["priority"],2), t.get("order",9999)))
    return ts

def display_tasks(d, parent_id, total):
    """Return pending tasks in strict priority order so same-priority tiles fill rows together."""
    return focus_tasks(d, parent_id)[:total]

# ── Helpers ────────────────────────────────────────────────────────────────────
def icon_btn(text, tooltip="", size=24):
    b = QPushButton(text)
    b.setFixedSize(size, size)
    b.setToolTip(tooltip)
    font_pt = max(7, size - 14)   # e.g. size=24 → 10pt, size=28 → 14pt
    b.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {DIM}; border: none; "
        f"font-size: {font_pt}pt; padding: 0; margin: 0; }}"
        f"QPushButton:hover {{ color: {TEXT}; background: {BTN}; border-radius: 5px; }}"
    )
    return b

def primary_btn(text):
    b = QPushButton(text)
    b.setStyleSheet(f"QPushButton {{ background: {ACCENT}; color: white; border: none; "
                    f"border-radius: 7px; padding: 7px 16px; font-weight: 600; }}"
                    f"QPushButton:hover {{ background: #7a72ff; }}"
                    f"QPushButton:pressed {{ background: #5a53ee; }}")
    return b

def list_ck(checked=False):
    """QCheckBox pre-styled transparent for coloured list row backgrounds."""
    ck = QCheckBox(); ck.setChecked(checked)
    ck.setStyleSheet(
        f"QCheckBox {{ background: transparent; }}"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; "
        f"border: 2px solid {BDR_H}; background: transparent; }}"
        f"QCheckBox::indicator:checked {{ background: {DONE_CLR}; border-color: {DONE_CLR}; }}"
    )
    return ck

def ghost_btn(text, color=DIM):
    b = QPushButton(text)
    b.setStyleSheet(f"QPushButton {{ background: transparent; color: {color}; border: 1px solid {color}44; "
                    f"border-radius: 7px; padding: 5px 12px; }}"
                    f"QPushButton:hover {{ background: {color}15; color: {TEXT}; }}")
    return b

# ═════════════════════════════════════════════════════════════════════════════
# Stage pill — colored label with popup stage selector
# ═════════════════════════════════════════════════════════════════════════════
class StagePill(QToolButton):
    def __init__(self, task, data, refresh_cb):
        super().__init__()
        self._task = task; self._data = data; self._refresh = refresh_cb
        self.setPopupMode(QToolButton.InstantPopup)
        self._rebuild_menu()
        self._update()

    def _rebuild_menu(self):
        m = QMenu(self)
        for s in self._data.get("stages", DEFAULT_STAGES):
            act = m.addAction(s["name"])
            act.setData(s["id"])
        m.triggered.connect(self._change)
        self.setMenu(m)

    def _change(self, action):
        self._task["stage"] = action.data()
        save(self._data)
        self._update()
        self._refresh()

    def _update(self):
        sc = stage_color(self._data, self._task["stage"])
        sn = stage_name(self._data, self._task["stage"])
        self.setText(sn + " ▾")
        self.setStyleSheet(
            f"QToolButton {{ background: {sc}; color: #ffffff; border: none; "
            f"border-radius: 8px; padding: 2px 10px; font-size: 7pt; font-weight: bold; }}"
            f"QToolButton:hover {{ background: {sc}cc; }}"
            f"QToolButton::menu-indicator {{ width: 0; }}"
        )

# ═════════════════════════════════════════════════════════════════════════════
# Tile card
# ═════════════════════════════════════════════════════════════════════════════
class TileCard(QFrame):
    def __init__(self, task, data, app, refresh_cb):
        super().__init__()
        self._task = task; self._data = data; self._app = app; self._refresh = refresh_cb
        self.setCursor(Qt.PointingHandCursor)
        self._build()

    def _build(self):
        acc = TILE_ACC.get(self._task["priority"], BDR_H)
        bg  = TILE_BG.get(self._task["priority"], BG3)
        self.setStyleSheet(
            f"TileCard {{ background: {bg}; border-radius: 12px; border: 1.5px solid {acc}70; }}"
            f"TileCard:hover {{ border-color: {acc}cc; }}"
        )
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Main content area — explicit bg so priority colour shows fully (not window bg)
        content = QWidget()
        content.setAttribute(Qt.WA_StyledBackground, True)
        content.setStyleSheet(f"background: {bg};")
        vlay = QVBoxLayout(content)
        vlay.setContentsMargins(12, 10, 8, 10)
        vlay.setSpacing(4)

        # Top row: title + cog + checkbox
        top = QHBoxLayout(); top.setSpacing(4)
        title_lbl = QLabel(self._task["title"])
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"color: {TEXT}; font-size: 10pt; font-weight: 600; background: transparent;")
        title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        cog = icon_btn("⚙", "Edit / Notes", 22)
        cog.clicked.connect(self._edit)

        ck = QCheckBox()
        ck.setChecked(self._task.get("completed", False))
        ck.stateChanged.connect(self._complete)
        ck.setStyleSheet(
            f"QCheckBox {{ background: transparent; }}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 9px; "
            f"border: 2px solid {acc}88; background: transparent; }}"
            f"QCheckBox::indicator:checked {{ background: {DONE_CLR}; border-color: {DONE_CLR}; }}"
        )

        top.addWidget(title_lbl)
        top.addWidget(cog)
        top.addWidget(ck)
        vlay.addLayout(top)

        # Subtask preview; fall back to notes if no subtasks
        subs = [t for t in self._data["tasks"] if t.get("parent_id") == self._task["id"]]
        pending_subs = [t for t in subs if not t.get("completed")]
        if pending_subs:
            for t in pending_subs[:3]:
                sl = QLabel(f"  ·  {t['title']}")
                sl.setStyleSheet(f"color: {DIM}; font-size: 8pt; background: transparent;")
                sl.setWordWrap(True)
                vlay.addWidget(sl)
            if len(pending_subs) > 3:
                more = QLabel(f"  ·  +{len(pending_subs)-3} more…")
                more.setStyleSheet(f"color: {DIM}; font-size: 7pt; background: transparent;")
                vlay.addWidget(more)
        else:
            notes = self._task.get("notes", "").strip()
            if notes:
                preview = notes[:120] + ("…" if len(notes) > 120 else "")
                nl = QLabel(preview)
                nl.setWordWrap(True)
                nl.setStyleSheet(f"color: {DIM}; font-size: 8pt; background: transparent;")
                vlay.addWidget(nl)

        vlay.addStretch()

        # Stage pill
        pill = StagePill(self._task, self._data, self._refresh)
        vlay.addWidget(pill, 0, Qt.AlignLeft)

        outer.addWidget(content, 1)

        # Right strip — top half: Skip ↓, bottom half: Replace ⇄
        # No outer border, no divider line; buttons carry their own radius and background.
        strip = QWidget()
        strip.setFixedWidth(30)
        strip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        strip.setStyleSheet("QWidget { background: transparent; }")
        sl = QVBoxLayout(strip); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(0)

        sk = QPushButton("↓")
        sk.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sk.setToolTip("Skip — push to back of queue")
        sk.setStyleSheet(
            f"QPushButton {{ background: {acc}30; color: {acc}; border: none; "
            f"border-top-right-radius: 12px; font-size: 13pt; padding: 0; margin: 0; }}"
            f"QPushButton:hover {{ background: {acc}55; }}"
        )
        sk.clicked.connect(self._skip)

        rp = QPushButton("⇄")
        rp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        rp.setToolTip("Replace — swap with another task of same priority")
        rp.setStyleSheet(
            f"QPushButton {{ background: {acc}18; color: {acc}; border: none; "
            f"border-bottom-right-radius: 12px; font-size: 10pt; padding: 0; margin: 0; }}"
            f"QPushButton:hover {{ background: {acc}40; }}"
        )
        rp.clicked.connect(self._replace)

        sl.addWidget(sk); sl.addWidget(rp)
        outer.addWidget(strip)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            dlg = SubtaskWindow(self.window(), self._task, self._data, self._app)
            self._app._open_window(dlg)

    def _complete(self, state):
        self._task["completed"] = bool(state)
        save(self._data); self._refresh(); self._app.refresh()

    def _skip(self):
        p_id = self._task.get("parent_id")
        peers = [t for t in self._data["tasks"]
                 if t.get("parent_id") == p_id and not t.get("completed") and not t.get("recurring")]
        mx = max((t.get("order", 0) for t in peers), default=0)
        self._task["order"] = mx + 1
        save(self._data); self._refresh()

    def _replace(self):
        ReplaceDialog(self.window(), self._task, self._data, self._app, self._refresh).exec_()

    def _edit(self):
        dlg = TaskDetailDialog(self.window(), self._task, self._data, self._app)
        dlg.accepted_sig.connect(self._refresh)
        dlg.exec_()

# ═════════════════════════════════════════════════════════════════════════════
# Tile grid — cached tiles, smooth live resize via reposition only
# ═════════════════════════════════════════════════════════════════════════════
class TileGrid(QWidget):
    def __init__(self, data, cfg, app, parent_id=None):
        super().__init__()
        self._data = data; self._cfg = cfg; self._app = app; self._pid = parent_id
        self._tiles: list = []   # cached TileCard widgets
        self._empty_lbl = None
        self.setStyleSheet(f"background: {BG2};")
        QTimer.singleShot(50, self.rebuild)   # initial populate after layout is ready

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition()       # instant — no timer, no widget creation

    def rebuild(self):
        """Call when underlying data changes. Recreates tile widgets, then repositions."""
        for t in self._tiles: t.deleteLater()
        self._tiles = []
        if self._empty_lbl:
            self._empty_lbl.deleteLater()
            self._empty_lbl = None

        # Cache ALL pending tasks as TileCards (hidden until positioned)
        tasks = display_tasks(self._data, self._pid, 9999)
        for t in tasks:
            tile = TileCard(t, self._data, self._app, self.rebuild)
            tile.setParent(self)
            tile.hide()
            self._tiles.append(tile)

        self._reposition()

    def _reposition(self):
        """Priority-grouped rows: each priority fills whole rows before the next starts."""
        w = self.width(); h = self.height()
        if w < 60: return

        if not self._tiles:
            if self._empty_lbl is None:
                self._empty_lbl = QLabel("All caught up  ✓\nNo pending tasks", self)
                self._empty_lbl.setAlignment(Qt.AlignCenter)
                self._empty_lbl.setStyleSheet(
                    f"color: {DIM}; font-size: 14pt; font-weight: 300; background: transparent;"
                )
            self._empty_lbl.setGeometry(0, 0, w, h)
            self._empty_lbl.show()
            return

        margin = 10; gap = 10
        ts   = self._cfg.get("tile_size", 220)
        cols = max(1, (w - 2*margin + gap) // (ts + gap))
        sz   = max(100, (w - 2*margin - gap*(cols - 1)) // cols)

        # Split into "featured" (up to cols per priority) and "overflow" (the rest).
        # Featured tiles fill rows in priority order, mixing priorities only when a
        # group has fewer tiles than cols (e.g. 2 medium + 1 low share a row of 3).
        # Overflow tiles are appended at the bottom in priority order.
        hi = [t for t in self._tiles if t._task["priority"] == "high"]
        me = [t for t in self._tiles if t._task["priority"] == "medium"]
        lo = [t for t in self._tiles if t._task["priority"] == "low"]

        featured = hi[:cols] + me[:cols] + lo[:cols]
        overflow = hi[cols:]  + me[cols:]  + lo[cols:]
        all_disp = featured + overflow

        shown = set()
        for i, tile in enumerate(all_disp):
            r, c = divmod(i, cols)
            x = margin + c * (sz + gap)
            y = margin + r * (sz + gap)
            if y + sz <= h:
                tile.setGeometry(x, y, sz, sz)
                tile.show()
                shown.add(id(tile))
            else:
                tile.hide()

        for tile in self._tiles:
            if id(tile) not in shown:
                tile.hide()

# ═════════════════════════════════════════════════════════════════════════════
# Recurring view — active + done sections, drag to reorder
# ═════════════════════════════════════════════════════════════════════════════
class RecurringTile(QFrame):
    drag_started = pyqtSignal(object)

    def __init__(self, task, data, app, refresh_cb):
        super().__init__()
        self._task = task; self._data = data; self._app = app; self._refresh = refresh_cb
        self._drag_pos = None
        acc = TILE_ACC.get(task["priority"], BDR_H)
        bg  = TILE_BG.get(task["priority"], BG3)
        self.setStyleSheet(f"RecurringTile {{ background: {bg}; border-radius: 10px; border: 1px solid {acc}40; }}"
                           f"RecurringTile:hover {{ border-color: {acc}70; }}")
        self._build(acc)

    def _build(self, acc):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignTop)

        top = QHBoxLayout(); top.setSpacing(4)
        tl = QLabel(self._task["title"])
        tl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 9pt; background: transparent;")
        tl.setWordWrap(True)
        ck = QCheckBox()
        ck.setChecked(self._task.get("completed", False))
        ck.stateChanged.connect(lambda s: self._toggle(s))
        ck.setStyleSheet(
            f"QCheckBox {{ background: transparent; }}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 9px; "
            f"border: 2px solid {acc}88; background: transparent; }}"
            f"QCheckBox::indicator:checked {{ background: {DONE_CLR}; border-color: {DONE_CLR}; }}"
        )
        top.addWidget(tl, 1); top.addWidget(ck)
        lay.addLayout(top)
        pill = StagePill(self._task, self._data, self._refresh)
        lay.addWidget(pill, 0, Qt.AlignLeft)
        lay.addStretch()

    def _toggle(self, state):
        self._task["completed"] = bool(state)
        save(self._data); self._refresh()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.pos()

    def mouseMoveEvent(self, e):
        if self._drag_pos and (e.pos() - self._drag_pos).manhattanLength() > 8:
            self._drag_pos = None
            self.drag_started.emit(self)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


class RecurringView(QScrollArea):
    def __init__(self, data, cfg, app):
        super().__init__()
        self._data = data; self._cfg = cfg; self._app = app
        self._dragging_task = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"background: {BG2};")
        self.rebuild()

    def rebuild(self):
        container = QWidget(); container.setStyleSheet(f"background: {BG2};")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        ts = self._cfg.get("tile_size", 220)
        w = max(self.width() - 30, ts)
        cols = max(1, w // (ts + 10))
        tile_sz = (w - 10 * (cols - 1)) // cols

        active = [t for t in self._data["tasks"] if t.get("recurring") and not t.get("completed")]
        done   = [t for t in self._data["tasks"] if t.get("recurring") and t.get("completed")]
        active.sort(key=lambda t: t.get("order", 9999))

        self._render_section(lay, "ACTIVE", active, tile_sz, cols, draggable=True)
        if done:
            sep = QFrame(); sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet(f"color: {BDR};"); lay.addWidget(sep)
            self._render_section(lay, "DONE", done, tile_sz, cols, draggable=False)

        lay.addStretch()
        self.setWidget(container)

    def _render_section(self, parent_lay, title, tasks, tile_sz, cols, draggable):
        hdr = QLabel(title)
        hdr.setStyleSheet(f"color: {DIM}; font-size: 7pt; font-weight: bold; letter-spacing: 2px;")
        parent_lay.addWidget(hdr)
        if not tasks:
            empty = QLabel("  Nothing here")
            empty.setStyleSheet(f"color: {DIM}; font-size: 8pt;")
            parent_lay.addWidget(empty)
            return
        grid = QGridLayout(); grid.setSpacing(10)
        for i, t in enumerate(tasks):
            r, c = divmod(i, cols)
            tile = RecurringTile(t, self._data, self._app, self.rebuild)
            tile.setFixedSize(tile_sz, tile_sz)
            if draggable:
                tile.drag_started.connect(self._on_drag_start)
            grid.addWidget(tile, r, c)
        for c in range(cols): grid.setColumnStretch(c, 1)
        parent_lay.addLayout(grid)

    def _on_drag_start(self, source_tile):
        self._dragging_task = source_tile._task
        self._source_tile = source_tile
        source_tile.setStyleSheet(source_tile.styleSheet() + "opacity: 0.4;")
        self.grabMouse()
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if self._dragging_task and event.type() == QEvent.MouseButtonRelease:
            global_pos = event.globalPos()
            target = self._find_tile_at(global_pos)
            if target and target._task is not self._dragging_task:
                src_order = self._dragging_task.get("order", 9999)
                self._dragging_task["order"] = target._task.get("order", 9999)
                target._task["order"] = src_order
                # Renumber cleanly
                active = [t for t in self._data["tasks"] if t.get("recurring") and not t.get("completed")]
                active.sort(key=lambda t: t.get("order", 9999))
                for i, t in enumerate(active): t["order"] = i
                save(self._data)
            self._dragging_task = None
            self.releaseMouse()
            self.removeEventFilter(self)
            self.rebuild()
            return True
        return False

    def _find_tile_at(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        while widget:
            if isinstance(widget, RecurringTile): return widget
            widget = widget.parent() if hasattr(widget, 'parent') else None
        return None

# ═════════════════════════════════════════════════════════════════════════════
# Image resize handle + custom text editor
# ═════════════════════════════════════════════════════════════════════════════
class _ImageHandle(QWidget):
    """Draggable grip shown at the bottom-right of a clicked image."""
    def __init__(self, viewport, editor, img_pos, img_w, img_tl):
        super().__init__(viewport)
        self._editor     = editor
        self._img_pos    = img_pos
        self._drag_start = None
        self._start_w    = img_w
        self.setFixedSize(14, 14)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setStyleSheet(
            f"background: {ACCENT}; border-radius: 3px; border: 1px solid white;"
        )
        # Place at estimated right edge of image
        x = min(img_tl.x() + img_w - 7,  viewport.width()  - 14)
        y = min(img_tl.y() + 60,          viewport.height() - 14)
        self.move(max(0, x), max(0, y))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = e.globalPos()
            self._start_w    = self._cur_w()

    def mouseMoveEvent(self, e):
        if self._drag_start:
            dx    = e.globalPos().x() - self._drag_start.x()
            new_w = max(40, self._start_w + dx)
            self._apply(new_w)

    def mouseReleaseEvent(self, e):
        self._drag_start = None

    def _cur_w(self):
        c = QTextCursor(self._editor.document())
        c.setPosition(self._img_pos)
        fmt = c.charFormat()
        try:
            return int(fmt.toImageFormat().width()) or 400
        except Exception:
            return 400

    def _apply(self, w):
        doc = self._editor.document()
        c = QTextCursor(doc)
        c.setPosition(self._img_pos)
        fmt = c.charFormat()
        img_fmt = fmt.toImageFormat()
        img_fmt.setWidth(w)
        c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
        c.mergeCharFormat(img_fmt)
        # Slide handle to new right-edge position
        vp = self.parent()
        c2 = QTextCursor(doc); c2.setPosition(self._img_pos)
        new_x = min(self._editor.cursorRect(c2).left() + w - 7, vp.width() - 14)
        self.move(max(0, new_x), self.y())


class NotesEditor(QTextEdit):
    """QTextEdit that shows a drag-to-resize handle when an image is clicked.
    Uses a viewport event filter so mouse coords match cursorForPosition expectations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img_handle = None
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is not self.viewport():
            return False
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._img_handle:
                self._img_handle.deleteLater()
                self._img_handle = None
            # Use U+FFFC (ObjectReplacementCharacter) detection — more reliable
            # than isImageFormat() when images are inserted via insertHtml.
            cursor = self.cursorForPosition(event.pos())
            img_cur = self._find_image(cursor)
            if img_cur is not None:
                fmt    = img_cur.charFormat()
                img_w  = 400
                try: img_w = int(fmt.toImageFormat().width()) or 400
                except Exception: pass
                r = self.cursorRect(img_cur)
                self._img_handle = _ImageHandle(
                    self.viewport(), self, img_cur.position(),
                    img_w, QPoint(r.left(), r.top()))
                self._img_handle.show()
        return False

    def _find_image(self, cursor):
        """Return a cursor positioned AT the image char, or None."""
        doc = self.document()
        pos = cursor.position()
        for p in (pos, pos - 1):
            if 0 <= p < doc.characterCount():
                # U+FFFC is the ObjectReplacementCharacter Qt uses for inline images
                if ord(doc.characterAt(p)) == 0xFFFC:
                    c = QTextCursor(doc)
                    c.setPosition(p)
                    return c
        return None

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self._img_handle:
            self._img_handle.deleteLater()
            self._img_handle = None


# ═════════════════════════════════════════════════════════════════════════════
# Notes view — multiple tabs, rich text, auto-save
# ═════════════════════════════════════════════════════════════════════════════
class NotesView(QWidget):
    def __init__(self, data, app):
        super().__init__()
        self._data = data; self._app = app
        self._save_timer = QTimer(); self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._autosave)
        self._cur_tab_id = None
        self._editors = {}       # tab_id -> QTextEdit
        self._tab_btns = {}      # tab_id -> QPushButton
        self.setStyleSheet(f"background: {BG2};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Sub-tab bar (horizontally scrollable) ─────────────────────────
        self._tab_scroll = QScrollArea()
        self._tab_scroll.setFrameShape(QFrame.NoFrame)
        self._tab_scroll.setFixedHeight(38)
        self._tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tab_scroll.setWidgetResizable(False)
        self._tab_scroll.setMinimumWidth(0)          # never force window wider
        self._tab_scroll.setStyleSheet(f"""
            QScrollArea {{ background: {BG}; border-bottom: 1px solid {BDR}; }}
            QScrollBar:horizontal {{
                background: {BG2}; height: 4px; border-radius: 2px; margin: 0; border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: {BDR_H}; border-radius: 2px; min-width: 20px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """)
        self._tab_bar = QWidget()
        self._tab_bar.setStyleSheet(f"background: {BG};")
        self._tab_bar.setMinimumWidth(0)             # allow any window width
        self._tbl = QHBoxLayout(self._tab_bar)
        self._tbl.setContentsMargins(8, 4, 8, 4); self._tbl.setSpacing(2)
        self._tbl.setSizeConstraint(QLayout.SetFixedSize)
        self._tab_scroll.setWidget(self._tab_bar)
        lay.addWidget(self._tab_scroll)

        # ── Formatting toolbar ─────────────────────────────────────────────
        tb = QWidget()
        tb.setStyleSheet(f"background: {BG3}; border-bottom: 1px solid {BDR};")
        tb_l = QHBoxLayout(tb); tb_l.setContentsMargins(8, 3, 8, 3); tb_l.setSpacing(2)
        for text, tip, fn in [
            ("H1","Heading 1", lambda: self._heading(1)),
            ("H2","Heading 2", lambda: self._heading(2)),
            ("H3","Heading 3", lambda: self._heading(3)),
            ("B", "Bold",      self._bold),
            ("I", "Italic",    self._italic),
            ("•", "Bullet",    self._bullet),
            ("🖼","Image",     self._insert_image),
            ("Aa","Normal",    self._normal),
        ]:
            b = QPushButton(text); b.setFixedSize(38, 30); b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{DIM};border:none;"
                f"font-size:11pt;padding:0;margin:0;}}"
                f"QPushButton:hover{{background:{BTN_H};color:{TEXT};border-radius:5px;}}"
            )
            b.clicked.connect(fn); tb_l.addWidget(b)
        tb_l.addStretch()
        lay.addWidget(tb)

        # ── Editor stack ───────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {BG3};")
        lay.addWidget(self._stack, 1)

        self._reload_tabs()

    def _reload_tabs(self):
        # Clear tab bar (keep + button logic below)
        while self._tbl.count():
            item = self._tbl.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        while self._stack.count():
            w = self._stack.widget(0); self._stack.removeWidget(w); w.deleteLater()
        self._editors.clear(); self._tab_btns.clear()

        for tab in self._data.get("notes_tabs", []):
            self._add_tab_ui(tab)

        # + button — no border-radius in resting state to avoid glyph clipping
        add = QPushButton("+"); add.setFixedSize(30, 28)
        add.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ACCENT};border:none;"
            f"font-size:15pt;font-weight:bold;padding:0;margin:0;}}"
            f"QPushButton:hover{{background:{BTN};border-radius:6px;}}")
        add.clicked.connect(self._add_tab)
        self._tbl.addWidget(add)
        # No addStretch — tab bar is self-sizing, scroll area handles overflow

        if self._data.get("notes_tabs"):
            self._switch_tab(self._data["notes_tabs"][0]["id"])

    def _add_tab_ui(self, tab):
        tid = tab["id"]
        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        btn = QPushButton(tab["name"]); btn.setCheckable(True); btn.setFixedHeight(28)
        btn.setStyleSheet(f"QPushButton{{background:transparent;color:{DIM};border:none;"
                          f"border-radius:6px 0 0 6px;padding:3px 10px;font-size:9pt;}}"
                          f"QPushButton:checked{{background:{BTN_H};color:{TEXT};}}"
                          f"QPushButton:hover{{color:{TEXT};}}")
        btn.clicked.connect(lambda _=False, t=tid: self._switch_tab(t))
        btn.mouseDoubleClickEvent = lambda e, t=tid: self._rename_tab(t)

        x = QPushButton("×"); x.setFixedSize(20, 28)
        x.setStyleSheet(f"QPushButton{{background:transparent;color:{DIM};border:none;"
                        f"border-radius:0 6px 6px 0;font-size:12pt;padding:0;}}"
                        f"QPushButton:hover{{color:#ff6060;background:{BTN_H};}}")
        x.clicked.connect(lambda _=False, t=tid: self._delete_tab(t))

        rl.addWidget(btn); rl.addWidget(x)
        self._tbl.addWidget(row)
        self._tab_btns[tid] = btn

        ed = NotesEditor(); ed.setAcceptRichText(True)
        ed.setStyleSheet(f"QTextEdit{{background:{BG3};border:none;padding:14px;font-size:10pt;}}")
        if tab.get("html"): ed.setHtml(tab["html"])
        ed.textChanged.connect(lambda t=tid: self._on_change(t))
        self._stack.addWidget(ed); self._editors[tid] = ed

    def _switch_tab(self, tid):
        self._autosave()
        self._cur_tab_id = tid
        for t, b in self._tab_btns.items(): b.setChecked(t == tid)
        if tid in self._editors: self._stack.setCurrentWidget(self._editors[tid])

    def _on_change(self, tid):
        if tid == self._cur_tab_id: self._save_timer.start(600)

    def _autosave(self):
        if not self._cur_tab_id: return
        ed = self._editors.get(self._cur_tab_id)
        if ed:
            for tab in self._data.get("notes_tabs", []):
                if tab["id"] == self._cur_tab_id:
                    tab["html"] = ed.toHtml(); break
            save(self._data)

    def _add_tab(self):
        t = {"id": str(uuid.uuid4()), "name": "New Tab", "html": ""}
        self._data["notes_tabs"].append(t); save(self._data)
        self._reload_tabs(); self._switch_tab(t["id"])

    def _rename_tab(self, tid):
        cur = next((t["name"] for t in self._data["notes_tabs"] if t["id"] == tid), "")
        name, ok = QInputDialog.getText(self, "Rename Tab", "Tab name:", text=cur)
        if ok and name.strip():
            for t in self._data["notes_tabs"]:
                if t["id"] == tid: t["name"] = name.strip()
            save(self._data)
            if tid in self._tab_btns: self._tab_btns[tid].setText(name.strip())

    def _delete_tab(self, tid):
        if len(self._data.get("notes_tabs", [])) <= 1: return
        self._autosave()
        self._data["notes_tabs"] = [t for t in self._data["notes_tabs"] if t["id"] != tid]
        save(self._data); self._reload_tabs()

    def load_content(self): pass  # auto-loaded from data on build

    def _ed(self): return self._editors.get(self._cur_tab_id)

    def _heading(self, level):
        ed = self._ed()
        if not ed: return
        cur = ed.textCursor(); fmt = QTextCharFormat()
        fmt.setFontPointSize({1:20,2:16,3:13}[level]); fmt.setFontWeight(QFont.Bold)
        cur.mergeCharFormat(fmt); ed.setTextCursor(cur)

    def _bold(self):
        ed = self._ed()
        if not ed: return
        cur = ed.textCursor(); fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if cur.charFormat().fontWeight() == QFont.Bold else QFont.Bold)
        cur.mergeCharFormat(fmt); ed.setTextCursor(cur)

    def _italic(self):
        ed = self._ed()
        if not ed: return
        cur = ed.textCursor(); fmt = QTextCharFormat()
        fmt.setFontItalic(not cur.charFormat().fontItalic())
        cur.mergeCharFormat(fmt); ed.setTextCursor(cur)

    def _bullet(self):
        ed = self._ed()
        if ed: ed.textCursor().insertList(QTextListFormat.ListDisc)

    def _normal(self):
        ed = self._ed()
        if not ed: return
        cur = ed.textCursor(); fmt = QTextCharFormat()
        fmt.setFontPointSize(10); fmt.setFontWeight(QFont.Normal); fmt.setFontItalic(False)
        cur.mergeCharFormat(fmt); ed.setTextCursor(cur)

    def _insert_image(self):
        ed = self._ed()
        if not ed: return
        path, _ = QFileDialog.getOpenFileName(self, "Select Image", "",
                                              "Images (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not path: return
        with open(path, "rb") as f: img_b64 = base64.b64encode(f.read()).decode()
        ext  = Path(path).suffix.lstrip(".").lower()
        mime = "jpeg" if ext in ("jpg","jpeg") else ext
        # Insert at a sensible default width; click the image to get a drag handle
        ed.insertHtml(f'<img src="data:image/{mime};base64,{img_b64}" width="400"><br>')

# ═════════════════════════════════════════════════════════════════════════════
# Drag bar + base dialog
# ═════════════════════════════════════════════════════════════════════════════
class DragBar(QWidget):
    def __init__(self, title, win, height=44, minimize=True):
        super().__init__(); self._win = win; self._dp = None
        self.setFixedHeight(height)
        lay = QHBoxLayout(self); lay.setContentsMargins(16, 0, 10, 0); lay.setSpacing(6)
        self._title = QLabel(title)
        self._title.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {TEXT};")
        lay.addWidget(self._title); lay.addStretch()
        self._meta = QLabel("")
        self._meta.setStyleSheet(f"color: {DIM}; font-size: 8pt;")
        lay.addWidget(self._meta)
        if minimize:
            mb = QPushButton("—"); mb.setFixedSize(32, 32)
            mb.setStyleSheet(f"QPushButton {{ background: transparent; color: {DIM}; border: none; "
                             f"border-radius: 8px; font-size: 12pt; }}"
                             f"QPushButton:hover {{ background: {BTN_H}; color: {TEXT}; }}")
            mb.clicked.connect(win.showMinimized); lay.addWidget(mb)
        cb = QPushButton("✕"); cb.setFixedSize(32, 32)
        cb.setStyleSheet(f"QPushButton {{ background: transparent; color: {DIM}; border: none; "
                         f"border-radius: 8px; font-size: 12pt; }}"
                         f"QPushButton:hover {{ background: #5a1818; color: #ff6060; }}")
        cb.clicked.connect(win.close); lay.addWidget(cb)
        self._lay = lay

    def set_meta(self, t): self._meta.setText(t)
    def set_title(self, t): self._title.setText(t)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._dp = e.globalPos() - self._win.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._dp: self._win.move(e.globalPos() - self._dp)
    def mouseReleaseEvent(self, e): self._dp = None
    def mouseDoubleClickEvent(self, e):
        self._win.showNormal() if self._win.isMaximized() else self._win.showMaximized()


class BaseDialog(QDialog):
    def __init__(self, parent, title, w=480, h=520):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(w, h)
        outer = QVBoxLayout(self); outer.setContentsMargins(10, 10, 10, 10); outer.setSpacing(0)
        self.frame = QFrame(); self.frame.setObjectName("dlgFrame")
        self.frame.setStyleSheet(f"#dlgFrame {{ background: {BG2}; border-radius: 12px; border: 1px solid {BDR}; }}")
        sh = QGraphicsDropShadowEffect(self); sh.setBlurRadius(30)
        sh.setColor(QColor(0,0,0,200)); sh.setOffset(0,5); self.frame.setGraphicsEffect(sh)
        outer.addWidget(self.frame)
        fl = QVBoxLayout(self.frame); fl.setContentsMargins(0,0,0,0); fl.setSpacing(0)
        self.bar = DragBar(title, self, 38, minimize=False)
        self.bar.setStyleSheet(f"DragBar {{ background: {BG}; border-top-left-radius: 12px; "
                               f"border-top-right-radius: 12px; border-bottom: 1px solid {BDR}; }}")
        fl.addWidget(self.bar)
        self.body = QWidget(); self.body.setStyleSheet(f"background: {BG2};")
        self._bl = QVBoxLayout(self.body); self._bl.setContentsMargins(20,16,20,20); self._bl.setSpacing(10)
        fl.addWidget(self.body, 1)

    def add(self, w): self._bl.addWidget(w)
    def add_lay(self, l): self._bl.addLayout(l)
    def add_stretch(self): self._bl.addStretch()

    def field_label(self, text):
        l = QLabel(text); l.setStyleSheet(f"color: {DIM}; font-size: 8pt; font-weight: bold;")
        return l

# ═════════════════════════════════════════════════════════════════════════════
# Add task dialog
# ═════════════════════════════════════════════════════════════════════════════
class AddTaskDialog(BaseDialog):
    def __init__(self, parent, data, app, parent_id=None, recurring=False):
        t = "Add Recurring" if recurring else ("Add Subtask" if parent_id else "Add Task")
        super().__init__(parent, t, 460, 400)
        self._data = data; self._app = app; self._pid = parent_id; self._rec = recurring
        self._build()

    def _build(self):
        self.add(self.field_label("TITLE"))
        self._title = QLineEdit(); self._title.setPlaceholderText("Task title…")
        self._title.returnPressed.connect(self._save); self.add(self._title)

        pr = QHBoxLayout(); pr.addWidget(QLabel("Priority:"))
        self._pgrp = QButtonGroup(self)
        for p in ("high", "medium", "low"):
            rb = QRadioButton(PL[p]); rb.setProperty("v", p)
            rb.setStyleSheet(f"color: {TILE_ACC[p]}; font-weight: bold;")
            if p == "medium": rb.setChecked(True)
            self._pgrp.addButton(rb); pr.addWidget(rb)
        pr.addStretch(); self.add_lay(pr)

        if not self._rec:
            sr = QHBoxLayout(); sr.addWidget(QLabel("Stage:"))
            self._stage = QComboBox()
            for s in self._data.get("stages", DEFAULT_STAGES): self._stage.addItem(s["name"], s["id"])
            sr.addWidget(self._stage); sr.addStretch(); self.add_lay(sr)
        else: self._stage = None

        self.add(self.field_label("NOTES (OPTIONAL)"))
        self._notes = QTextEdit(); self._notes.setFixedHeight(70)
        self.add(self._notes); self.add_stretch()

        br = QHBoxLayout()
        sb = primary_btn("Add Task"); sb.clicked.connect(self._save)
        cb = ghost_btn("Cancel"); cb.clicked.connect(self.reject)
        br.addWidget(sb); br.addStretch(); br.addWidget(cb); self.add_lay(br)
        self._title.setFocus()

    def _save(self):
        title = self._title.text().strip()
        if not title: return
        checked = self._pgrp.checkedButton()
        t = mk_task(title, checked.property("v") if checked else "medium", self._pid, self._rec)
        if self._stage: t["stage"] = self._stage.currentData()
        t["notes"] = self._notes.toPlainText()
        self._data["tasks"].append(t)
        save(self._data); self._app.refresh(); self.accept()

# ═════════════════════════════════════════════════════════════════════════════
# Task detail dialog
# ═════════════════════════════════════════════════════════════════════════════
class TaskDetailDialog(BaseDialog):
    accepted_sig = pyqtSignal()

    def __init__(self, parent, task, data, app):
        super().__init__(parent, "Edit Task", 480, 540)
        self._task = task; self._data = data; self._app = app; self._build()

    def _build(self):
        self.add(self.field_label("TITLE"))
        self._te = QLineEdit(self._task["title"]); self.add(self._te)

        pr = QHBoxLayout(); pr.addWidget(QLabel("Priority:"))
        self._pgrp = QButtonGroup(self)
        for p in ("high", "medium", "low"):
            rb = QRadioButton(PL[p]); rb.setProperty("v", p)
            rb.setStyleSheet(f"color: {TILE_ACC[p]}; font-weight: bold;")
            if self._task["priority"] == p: rb.setChecked(True)
            self._pgrp.addButton(rb); pr.addWidget(rb)
        pr.addStretch(); self.add_lay(pr)

        sr = QHBoxLayout(); sr.addWidget(QLabel("Stage:"))
        self._stage = QComboBox()
        for s in self._data.get("stages", DEFAULT_STAGES):
            self._stage.addItem(s["name"], s["id"])
            if s["id"] == self._task["stage"]: self._stage.setCurrentIndex(self._stage.count()-1)
        sr.addWidget(self._stage); sr.addStretch(); self.add_lay(sr)

        self.add(self.field_label("NOTES"))
        self._notes = QTextEdit(self._task.get("notes",""))
        self._notes.setMinimumHeight(120); self.add(self._notes); self.add_stretch()

        br = QHBoxLayout()
        sv = primary_btn("Save"); sv.clicked.connect(self._save)
        dl = ghost_btn("Delete", "#ff607a"); dl.clicked.connect(self._delete)
        cl = ghost_btn("Cancel"); cl.clicked.connect(self.reject)
        br.addWidget(sv); br.addWidget(dl); br.addStretch(); br.addWidget(cl); self.add_lay(br)
        self._te.setFocus()

    def _save(self):
        t = self._title_val() or self._task["title"]
        self._task["title"] = t
        checked = self._pgrp.checkedButton()
        if checked: self._task["priority"] = checked.property("v")
        self._task["stage"] = self._stage.currentData()
        self._task["notes"] = self._notes.toPlainText()
        save(self._data); self._app.refresh(); self.accepted_sig.emit(); self.accept()

    def _title_val(self): return self._te.text().strip()

    def _delete(self):
        box = QMessageBox(self)
        box.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        box.setStyleSheet(f"background:{BG2}; color:{TEXT};")
        box.setText(f"Delete  '{self._task['title']}'?")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if box.exec_() == QMessageBox.Yes:
            self._data["tasks"] = [x for x in self._data["tasks"] if x["id"] != self._task["id"]]
            save(self._data); self._app.refresh(); self.accepted_sig.emit(); self.accept()

# ═════════════════════════════════════════════════════════════════════════════
# Full list dialog
# ═════════════════════════════════════════════════════════════════════════════
class FullListDialog(BaseDialog):
    def __init__(self, parent, data, app):
        super().__init__(parent, "All Tasks", 700, 640)
        self._data = data; self._app = app; self._build()

    def _build(self):
        ab = primary_btn("+ Add Task"); ab.clicked.connect(self._add)
        self.bar._lay.insertWidget(self.bar._lay.count()-1, ab)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.add(scroll)
        self._lw = QWidget(); self._lw.setStyleSheet(f"background:{BG2};")
        self._ll = QVBoxLayout(self._lw); self._ll.setContentsMargins(0,0,0,0); self._ll.setSpacing(3)
        scroll.setWidget(self._lw); self._render()

    def _render(self):
        while self._ll.count():
            item = self._ll.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for prio, hdr in [("high","HIGH PRIORITY"),("medium","MEDIUM PRIORITY"),("low","LOW PRIORITY")]:
            ts = [t for t in self._data["tasks"] if t["priority"]==prio and not t.get("recurring") and not t.get("parent_id")]
            ts.sort(key=lambda t:(t.get("completed",False), t.get("order",9999)))
            if not ts: continue
            hl = QLabel(f"  {hdr}"); hl.setStyleSheet(
                f"color:{TILE_ACC[prio]}; font-size:7pt; font-weight:bold; letter-spacing:2px; "
                f"background:{BG}; padding:8px 4px 6px;")
            self._ll.addWidget(hl)
            for t in ts: self._ll.addWidget(self._make_row(t))
        self._ll.addStretch()

    def _make_row(self, t):
        sc = stage_color(self._data, t["stage"])
        row = QFrame(); row.setStyleSheet(f"QFrame{{background:{TILE_BG.get(t['priority'],BG3)};border-radius:7px;}}")
        lay = QHBoxLayout(row); lay.setContentsMargins(6,3,6,3); lay.setSpacing(8)
        acc_bar = QFrame(); acc_bar.setFixedSize(3,26)
        acc_bar.setStyleSheet(f"background:{sc};border-radius:2px;border:none;"); lay.addWidget(acc_bar)
        ck = list_ck(t.get("completed", False))
        def tog(s, task=t): task["completed"]=bool(s); save(self._data); self._app.refresh(); self._app.update_meta(); self._render()
        ck.stateChanged.connect(tog); lay.addWidget(ck)
        tl = QLabel(t["title"]); done_s = "text-decoration:line-through;" if t.get("completed") else ""
        tl.setStyleSheet(f"color:{DIM if t.get('completed') else TEXT};{done_s}background:transparent;")
        tl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); lay.addWidget(tl)
        eb = ghost_btn("Edit", DIM)
        def do_edit(task=t):
            dlg = TaskDetailDialog(self, task, self._data, self._app)
            dlg.accepted_sig.connect(self._render); dlg.exec_()
        eb.clicked.connect(lambda _checked, f=do_edit: f()); lay.addWidget(eb)
        return row

    def _add(self):
        dlg = AddTaskDialog(self, self._data, self._app)
        dlg.accepted.connect(self._render); dlg.exec_()

# ═════════════════════════════════════════════════════════════════════════════
# Subtask windows
# ═════════════════════════════════════════════════════════════════════════════
class SubtaskWindow(BaseDialog):
    def __init__(self, parent, ptask, data, app):
        super().__init__(parent, f"⊞  {ptask['title'][:42]}", 860, 600)
        self._ptask = ptask; self._data = data; self._app = app
        self._cfg = load_cfg(); self._build()

    def _build(self):
        ab = primary_btn("+ Add Subtask"); ab.clicked.connect(self._add)
        lb = ghost_btn("☰ All Subtasks"); lb.clicked.connect(self._list)
        self.bar._lay.insertWidget(self.bar._lay.count()-1, lb)
        self.bar._lay.insertWidget(self.bar._lay.count()-1, ab)
        self._grid = TileGrid(self._data, self._cfg, self._app, self._ptask["id"])
        self.add(self._grid)

    def _add(self):
        dlg = AddTaskDialog(self, self._data, self._app, self._ptask["id"])
        dlg.accepted.connect(self._refresh); dlg.exec_()

    def _list(self):
        dlg = SubtaskListDialog(self, self._ptask, self._data, self._app)
        self._app._open_window(dlg)

    def _refresh(self): self._grid.rebuild()

    def _render(self): self._grid.rebuild()  # called by app.refresh()


class SubtaskListDialog(BaseDialog):
    def __init__(self, parent, ptask, data, app):
        super().__init__(parent, f"Subtasks: {ptask['title'][:35]}", 620, 500)
        self._ptask = ptask; self._data = data; self._app = app; self._build()

    def _build(self):
        ab = primary_btn("+ Add"); ab.clicked.connect(self._add)
        self.bar._lay.insertWidget(self.bar._lay.count()-1, ab)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        self.add(sc)
        self._lw = QWidget(); self._lw.setStyleSheet(f"background:{BG2};")
        self._ll = QVBoxLayout(self._lw); self._ll.setContentsMargins(0,0,0,0); self._ll.setSpacing(3)
        sc.setWidget(self._lw); self._render()

    def _render(self):
        while self._ll.count():
            item = self._ll.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        subs = [t for t in self._data["tasks"] if t.get("parent_id")==self._ptask["id"]]
        subs.sort(key=lambda t:(t.get("completed",False),{"high":0,"medium":1,"low":2}.get(t["priority"],2)))
        for t in subs:
            sc = stage_color(self._data, t["stage"])
            row = QFrame(); row.setStyleSheet(f"QFrame{{background:{TILE_BG.get(t['priority'],BG3)};border-radius:7px;}}")
            lay = QHBoxLayout(row); lay.setContentsMargins(6,3,6,3); lay.setSpacing(8)
            ck = list_ck(t.get("completed", False))
            def tog(s, task=t):
                task["completed"] = bool(s); save(self._data)
                self._app.refresh(); self._render()
            ck.stateChanged.connect(tog); lay.addWidget(ck)
            tl = QLabel(t["title"]); done_s="text-decoration:line-through;" if t.get("completed") else ""
            tl.setStyleSheet(f"color:{DIM if t.get('completed') else TEXT};{done_s}background:transparent;")
            tl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); lay.addWidget(tl)
            eb = ghost_btn("Edit", DIM)
            def do_edit(task=t):
                dlg = TaskDetailDialog(self, task, self._data, self._app)
                dlg.accepted_sig.connect(self._render); dlg.exec_()
            eb.clicked.connect(lambda _c, f=do_edit: f()); lay.addWidget(eb)
            self._ll.addWidget(row)
        self._ll.addStretch()

    def _add(self):
        dlg = AddTaskDialog(self, self._data, self._app, self._ptask["id"])
        dlg.accepted.connect(self._render); dlg.exec_()

    def _render(self): self._render()  # alias so app.refresh() can call it
    # override properly:
    def _render(self):
        while self._ll.count():
            item = self._ll.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        subs = [t for t in self._data["tasks"] if t.get("parent_id")==self._ptask["id"]]
        subs.sort(key=lambda t:(t.get("completed",False),{"high":0,"medium":1,"low":2}.get(t["priority"],2)))
        for t in subs:
            sc = stage_color(self._data, t["stage"])
            row = QFrame(); row.setStyleSheet(f"QFrame{{background:{TILE_BG.get(t['priority'],BG3)};border-radius:7px;}}")
            lay = QHBoxLayout(row); lay.setContentsMargins(6,3,6,3); lay.setSpacing(8)
            ck = list_ck(t.get("completed", False))
            def tog(s, task=t):
                task["completed"] = bool(s); save(self._data)
                self._app.refresh(); self._render()
            ck.stateChanged.connect(tog); lay.addWidget(ck)
            tl = QLabel(t["title"]); done_s="text-decoration:line-through;" if t.get("completed") else ""
            tl.setStyleSheet(f"color:{DIM if t.get('completed') else TEXT};{done_s}background:transparent;")
            tl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); lay.addWidget(tl)
            eb = ghost_btn("Edit", DIM)
            def do_edit(task=t):
                dlg = TaskDetailDialog(self, task, self._data, self._app)
                dlg.accepted_sig.connect(self._render); dlg.exec_()
            eb.clicked.connect(lambda _c, f=do_edit: f()); lay.addWidget(eb)
            self._ll.addWidget(row)
        self._ll.addStretch()

# ═════════════════════════════════════════════════════════════════════════════
# Settings dialog
# ═════════════════════════════════════════════════════════════════════════════
class SettingsDialog(BaseDialog):
    def __init__(self, parent, data, cfg, app):
        super().__init__(parent, "Settings", 540, 680)
        self._data = data; self._cfg = cfg; self._app = app; self._build()

    def _build(self):
        self.add(self.field_label("TILE SIZE  (window width ÷ tile size = columns)"))
        tr = QHBoxLayout(); tr.addWidget(QLabel("Tile size (px):"))
        self._ts = QSpinBox(); self._ts.setRange(140, 400); self._ts.setValue(self._cfg.get("tile_size",220))
        self._ts.setFixedWidth(80); tr.addWidget(self._ts); tr.addStretch(); self.add_lay(tr)

        # ── Priority colours ───────────────────────────────────────────────
        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine); sep0.setStyleSheet(f"color:{BDR};"); self.add(sep0)
        self.add(self.field_label("PRIORITY COLOURS"))
        ph = QLabel("Left swatch = tile background · Right swatch = accent / text colour")
        ph.setStyleSheet(f"color:{DIM}; font-size:8pt;"); self.add(ph)

        self._prio_cvs = {}
        for prio, label in [("high","High"), ("medium","Medium"), ("low","Low")]:
            r = QHBoxLayout()
            r.addWidget(QLabel(f"{label}:"))
            bg_cv  = [TILE_BG[prio]]
            acc_cv = [TILE_ACC[prio]]

            def _swatch(cv, parent=self):
                btn = QPushButton(); btn.setFixedSize(36, 26)
                btn.setStyleSheet(f"background:{cv[0]};border-radius:6px;border:none;")
                def pick(checked=False, b=btn, c=cv):
                    res = QColorDialog.getColor(QColor(c[0]), parent)
                    if res.isValid():
                        c[0] = res.name()
                        b.setStyleSheet(f"background:{res.name()};border-radius:6px;border:none;")
                btn.clicked.connect(pick)
                return btn

            r.addWidget(_swatch(bg_cv));  r.addWidget(QLabel("bg"))
            r.addWidget(_swatch(acc_cv)); r.addWidget(QLabel("accent"))
            r.addStretch()
            self._prio_cvs[prio] = (bg_cv, acc_cv)
            self.add_lay(r)

        # ── Progress stages ────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet(f"color:{BDR};"); self.add(sep)
        self.add(self.field_label("PROGRESS STAGES"))
        hint = QLabel("Click swatch to change colour.  Stages are shown on each tile's pill.")
        hint.setStyleSheet(f"color:{DIM}; font-size:8pt;"); self.add(hint)

        self._srows = []
        for s in self._data.get("stages", DEFAULT_STAGES):
            r = QHBoxLayout()
            ne = QLineEdit(s["name"]); ne.setFixedWidth(180)
            sw = QPushButton(); sw.setFixedSize(30,26)
            cv = [s["color"]]
            sw.setStyleSheet(f"background:{s['color']};border-radius:6px;border:none;")
            def pick(btn=sw, c=cv): res=QColorDialog.getColor(QColor(c[0]),self); \
                (res.isValid() and [c.__setitem__(0,res.name()), btn.setStyleSheet(f"background:{res.name()};border-radius:6px;border:none;")])
            sw.clicked.connect(pick)
            del_btn = ghost_btn("✕", "#ff607a"); del_btn.setFixedSize(26,26)
            def do_del(sid=s["id"]):
                self._data["stages"] = [x for x in self._data["stages"] if x["id"] != sid]
                save(self._data); self.reject()
                SettingsDialog(self._app, self._data, self._cfg, self._app).exec_()
            del_btn.clicked.connect(lambda _c, f=do_del: f())
            r.addWidget(ne); r.addWidget(sw); r.addWidget(del_btn); r.addStretch()
            self._srows.append((s["id"],ne,cv)); self.add_lay(r)

        ab = ghost_btn("+ Add Stage"); ab.clicked.connect(self._add_stage); self.add(ab)
        self.add_stretch()
        br = QHBoxLayout()
        sv = primary_btn("Save"); sv.clicked.connect(self._save)
        cl = ghost_btn("Cancel"); cl.clicked.connect(self.reject)
        br.addWidget(sv); br.addStretch(); br.addWidget(cl); self.add_lay(br)

        # ── Version ────────────────────────────────────────────────────────
        ver = QLabel(f"TileDo  v{APP_VERSION}")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet(f"color:{DIM}; font-size:8pt; background:transparent;")
        self.add(ver)

    def _add_stage(self):
        new_id = f"stage_{len(self._data['stages'])}"
        self._data["stages"].append({"id":new_id,"name":"New Stage","color":"#888899"})
        self.reject(); SettingsDialog(self._app,self._data,self._cfg,self._app).exec_()

    def _save(self):
        self._cfg["tile_size"] = self._ts.value()
        # Apply priority colours to module-level globals (TileCard reads these)
        for prio, (bg_cv, acc_cv) in self._prio_cvs.items():
            TILE_BG[prio]  = bg_cv[0]
            TILE_ACC[prio] = acc_cv[0]
        for sid,ne,cv in self._srows:
            for s in self._data["stages"]:
                if s["id"]==sid:
                    n=ne.text().strip()
                    if n: s["name"]=n
                    s["color"]=cv[0]
        save(self._data); save_cfg(self._cfg); self._app.refresh(); self.accept()

# ═════════════════════════════════════════════════════════════════════════════
# Replace dialog — swap a visible tile with a queued task
# ═════════════════════════════════════════════════════════════════════════════
class ReplaceDialog(BaseDialog):
    def __init__(self, parent, cur_task, data, app, refresh_cb):
        super().__init__(parent, f"Replace: {cur_task['title'][:38]}", 640, 540)
        self._cur = cur_task; self._data = data; self._app = app; self._cb = refresh_cb
        self._build()

    def _build(self):
        hint = QLabel("Select a task to show in this tile's place — the current tile moves to the queue.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {DIM}; font-size: 9pt;"); self.add(hint)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.add(scroll)
        lw = QWidget(); lw.setStyleSheet(f"background: {BG2};")
        ll = QVBoxLayout(lw); ll.setContentsMargins(0, 4, 0, 4); ll.setSpacing(5)
        scroll.setWidget(lw)

        tasks = [t for t in self._data["tasks"]
                 if not t.get("completed") and not t.get("recurring")
                 and t.get("parent_id") == self._cur.get("parent_id")
                 and t["id"] != self._cur["id"]
                 and t["priority"] == self._cur["priority"]]
        tasks.sort(key=lambda t: ({"high":0,"medium":1,"low":2}.get(t["priority"],2), t.get("order",9999)))

        if not tasks:
            ll.addWidget(QLabel("  No other tasks available.")); ll.addStretch()
        else:
            for t in tasks:
                row = QFrame()
                row.setStyleSheet(f"QFrame{{background:{TILE_BG.get(t['priority'],BG3)};border-radius:8px;}}")
                rl = QHBoxLayout(row); rl.setContentsMargins(8,5,8,5); rl.setSpacing(8)
                pc = TILE_ACC.get(t["priority"], DIM)
                tag = QLabel(PL.get(t["priority"],"?"))
                tag.setStyleSheet(f"color:{pc};font-weight:bold;font-size:8pt;background:transparent;")
                tag.setFixedWidth(30)
                tl = QLabel(t["title"]); tl.setStyleSheet(f"color:{TEXT};background:transparent;")
                tl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                sel = primary_btn("Select"); sel.setFixedHeight(28)
                def do_swap(task=t):
                    # Renumber peers so we get clean integer orders
                    peers = [x for x in self._data["tasks"]
                             if not x.get("completed") and not x.get("recurring")
                             and x.get("parent_id") == self._cur.get("parent_id")]
                    peers.sort(key=lambda x: x.get("order", 9999))
                    for i, p in enumerate(peers): p["order"] = i * 10
                    # Swap orders between current and target
                    cur_o, tgt_o = self._cur["order"], task["order"]
                    self._cur["order"] = tgt_o
                    task["order"] = cur_o
                    save(self._data); self._app.refresh(); self._cb(); self.accept()
                sel.clicked.connect(lambda _c, f=do_swap: f())
                rl.addWidget(tag); rl.addWidget(tl); rl.addWidget(sel)
                ll.addWidget(row)
            ll.addStretch()

        cl = ghost_btn("Cancel"); cl.clicked.connect(self.reject); self.add(cl)

# ═════════════════════════════════════════════════════════════════════════════
# Main window
# ═════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._data = load(); self._cfg = load_cfg()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self._cfg.get("w",980), self._cfg.get("h",740))
        self.move(self._cfg.get("x",100), self._cfg.get("y",60))
        self._child_windows = []
        self._build(); self.update_meta()

    def _build(self):
        central = QWidget(); central.setStyleSheet("background:transparent;")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central); outer.setContentsMargins(10,10,10,10); outer.setSpacing(0)

        self._frame = QFrame(); self._frame.setObjectName("mf")
        self._frame.setStyleSheet(f"#mf{{background:{BG2};border-radius:14px;border:1px solid {BDR};}}")
        sh = QGraphicsDropShadowEffect(self); sh.setBlurRadius(40)
        sh.setColor(QColor(0,0,0,210)); sh.setOffset(0,6); self._frame.setGraphicsEffect(sh)
        outer.addWidget(self._frame)

        fl = QVBoxLayout(self._frame); fl.setContentsMargins(0,0,0,0); fl.setSpacing(0)

        # Title bar
        self._bar = DragBar("TileDo", self, 46)
        self._bar.setStyleSheet(f"DragBar{{background:{BG};border-top-left-radius:14px;"
                                f"border-top-right-radius:14px;border-bottom:1px solid {BDR};}}")
        fl.addWidget(self._bar)

        # Tab bar
        tb = QWidget(); tb.setFixedHeight(42)
        tb.setStyleSheet(f"background:{BG};border-bottom:1px solid {BDR};")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(12,0,12,0); tbl.setSpacing(4)

        self._tab_btns = {}
        for key, label in (("todo","To Do"), ("recurring","Recurring"), ("notes","Notes")):
            btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(30)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{DIM};border:none;border-radius:7px;padding:4px 14px;}}"
                f"QPushButton:hover{{color:{TEXT};}}"
                f"QPushButton:checked{{background:{BTN_H};color:{TEXT};font-weight:600;}}"
            )
            btn.clicked.connect(lambda _, k=key: self._switch_tab(k))
            tbl.addWidget(btn); self._tab_btns[key] = btn

        tbl.addStretch()
        add_btn = primary_btn("＋  Add Task"); add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._add_task); tbl.addWidget(add_btn)
        all_btn = ghost_btn("☰  All Tasks"); all_btn.setFixedHeight(30)
        all_btn.clicked.connect(self._all_tasks); tbl.addWidget(all_btn)
        cfg_btn = QPushButton("⚙"); cfg_btn.setFixedSize(34, 30)
        cfg_btn.setToolTip("Settings")
        cfg_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {DIM}; border: 1px solid {DIM}44; "
            f"border-radius: 7px; font-size: 13pt; padding: 0; margin: 0; }}"
            f"QPushButton:hover {{ background: {BTN_H}; color: {TEXT}; border-color: {BDR_H}; }}"
        )
        cfg_btn.clicked.connect(self._settings); tbl.addWidget(cfg_btn)
        fl.addWidget(tb)

        # Stacked views
        self._stack = QStackedWidget(); self._stack.setStyleSheet(f"background:{BG2};")
        self._todo_view = TileGrid(self._data, self._cfg, self)
        self._rec_view  = RecurringView(self._data, self._cfg, self)
        self._notes_view = NotesView(self._data, self)
        self._stack.addWidget(self._todo_view)
        self._stack.addWidget(self._rec_view)
        self._stack.addWidget(self._notes_view)
        fl.addWidget(self._stack, 1)

        # Resize grip
        gr = QHBoxLayout(); gr.setContentsMargins(0,0,4,4); gr.addStretch()
        grip = QSizeGrip(self._frame); grip.setStyleSheet("background:transparent;")
        gr.addWidget(grip); fl.addLayout(gr)

        self._switch_tab("todo")

    def _switch_tab(self, key):
        idx = {"todo":0,"recurring":1,"notes":2}[key]
        self._stack.setCurrentIndex(idx)
        for k, b in self._tab_btns.items(): b.setChecked(k == key)
        if key == "notes": self._notes_view.load_content()
        if key == "recurring": self._rec_view.rebuild()

    def _open_window(self, dlg):
        """Show a non-modal window and track it for refresh."""
        self._child_windows.append(dlg)
        dlg.show(); dlg.raise_(); dlg.activateWindow()

    def refresh(self):
        self._todo_view.rebuild()
        if self._stack.currentIndex() == 1: self._rec_view.rebuild()
        self.update_meta()
        # Refresh all open child windows
        for w in list(self._child_windows):
            if not w.isVisible():
                self._child_windows.remove(w)
            elif hasattr(w, '_render'):
                w._render()

    def update_meta(self):
        n = sum(1 for t in self._data["tasks"] if not t.get("completed") and not t.get("recurring"))
        self._bar.set_meta(f"{n} pending")

    def _add_task(self):
        idx = self._stack.currentIndex()
        if idx == 1:
            AddTaskDialog(self, self._data, self, recurring=True).exec_()
        else:
            AddTaskDialog(self, self._data, self).exec_()

    def _all_tasks(self):
        dlg = FullListDialog(self, self._data, self)
        self._open_window(dlg)

    def _settings(self): SettingsDialog(self, self._data, self._cfg, self).exec_()

    def closeEvent(self, e):
        p = self.pos(); s = self.size()
        self._cfg.update({"x":p.x(),"y":p.y(),"w":s.width(),"h":s.height()})
        save_cfg(self._cfg); e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(SS)
    app.setApplicationName("TileDo")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
