# TileDo — project notes for Claude

TileDo is a single-file PyQt5 desktop task app (`tiledo.py`) built for engineering
work: projects → stages → nested jobs, recurring checklists, and rich-text reference
notes. Frameless charcoal/amber UI (design language borrowed from factory-planner).
It replaces Windows Sticky Notes for its owner and runs on a work PC from a GitHub
release. Everything a session needs is in this repo — there is no other context.

## Working on it
- **Python:** PyQt5 is installed on **3.12 only** — always `py -3.12`. The bare `py`
  launcher resolves to 3.14, which has no PyQt5. The `.bat` files already pin 3.12.
- Run from source: `test.bat` (= `py -3.12 tiledo.py`).
- Safe testing: `TILEDO_DATA_DIR=<temp dir>` redirects all data files;
  `QT_QPA_PLATFORM=offscreen` lets a script build the windows headlessly (the global
  hotkey is skipped in that mode). Pattern: set both env vars, `import tiledo as T`,
  build `T.MainWindow()`, drive `navigate()` / `refresh()`, inspect `_grid._items`.
  After a rebuild call `app.sendPostedEvents(None, QEvent.DeferredDelete)` before
  counting widgets, otherwise `deleteLater()` zombies are still there.
- Dialogs block (`exec_()`); in tests monkey-patch `ConfirmDialog.exec_` /
  `TextPromptDialog.exec_` + `.value` to drive them.
- Local exe build: `build.bat` (PyInstaller one-file). CI does the real build.

## Versioning and release — important
- `APP_VERSION` in `tiledo.py` is the single source of truth. **Bump it on every
  change** without being asked: patch = fix, minor = feature, major = redesign.
- Push to `main` → GitHub Actions (`.github/workflows/build.yml`) builds `TileDo.exe`
  and overwrites the rolling **`latest`** release, titled `TileDo v<APP_VERSION>`.
  The in-app updater (Settings → Check for updates) parses that title, so the title
  format and the asset name `TileDo.exe` must never change.
- Pushing a `v*` tag additionally creates a named release.
- The work PC installs from `releases/tag/latest` and self-updates from Settings.
- Workflow for a change: edit → offscreen smoke test → bump version → commit → push
  `main` → wait ~2 min for the release.

## Data (`~/.tiledo/`)
- `data.json`: `tasks[]`, `stages[]`, `templates[]`.
  Task fields: `id, title, notes, priority (high|medium|low), stage (stage id),
  parent_id, recurring, completed, order, created`; optional
  `waiting {note, since, prev_stage}`; optional `view` (`"list"` → the task's
  children render as compact rows instead of tiles).
- `notes.json` (rich-text pages), `settings.json`, `archive.json` (archived
  subtrees; archive roots carry `archived_at`).
- Writes are atomic (`.tmp` + rename) with a `.bak` fallback on read. v1 data
  auto-migrates in `load_data()`.
- Stages are user-editable. Find the semantic ones with `blocked_stage_id()` and
  `progress_stage_id()` (stock id first, then name match) — never hard-code
  `"blocked"` / `"in_progress"` anywhere else.

## Behaviour rules worth knowing
- **Waiting ⇔ Blocked are paired.** `set_waiting()` moves a task to the Blocked
  stage and remembers `prev_stage`; `clear_waiting()` restores it; moving a task off
  Blocked drops the wait; choosing Blocked on a stage chip prompts for a reason.
  The reason is shown as the tile's subtext.
- **Display order inside a priority bucket** is `stage_ranker()`: in progress →
  everything else → blocked/waiting, then manual `order`. New tasks get
  `max(order)+10`, so they land after the open tasks and before the blocked ones.
  `bucket()` sorts the same way so renumbering after a drag keeps the groups; a drag
  across groups lands at the edge of the dragged card's own group.
- **Drag-and-drop:** `CardGrid.drag_started()` hides the dragged card and
  `set_gap()` opens a landing gap at the hovered position (iOS home-screen style);
  `_GridBox` accepts drops into the gap or the empty space after the last card.
  Tiles judge the zone by x (before / after / nest), compact rows by y.
- **Dialogs:** Save / OK / Add are the default buttons (Enter). The destructive
  `ConfirmDialog` defaults to Cancel. Esc rejects everywhere.
- **Undo** is snapshot based: call `snapshot()` before every mutation (Ctrl+Z pops,
  30 deep); use `snapshot(include_archive=True)` when touching `archive.json`.
- Single instance via QLocalServer IPC (`tiledo-ipc`); `--tray` starts hidden;
  global **Ctrl+Alt+T** quick capture (RegisterHotKey) lands in the open or
  last-opened task by default, with a target picker.
- Completed children show in a strip under the drilled view: 4 rows, "Show all",
  per-row and bulk archive.

## Map of `tiledo.py`
data layer + tree helpers + waiting/blocked helpers → stylesheet → small widgets
(`StageChip`, `TinyProgress`) → `TaskCard` (tile and compact row) → `_GridBox` /
`CardGrid` → breadcrumb + frameless chrome → dialogs → `TaskWindow` (pop-out) →
notes editor → updater → `SettingsDialog` → hotkey + `QuickCaptureDialog` →
`MainWindow` → `main()`.

## Roadmap
`docs/V3_HANDOVER.md` is the agreed design for V3: a multi-user, Firebase-backed web
rebuild. The PyQt5 app stays on v2.x (fixes only) until V3 is in daily use.
