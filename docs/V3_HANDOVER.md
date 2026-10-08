# TileDo V3 — handover and design brief

**Status:** design agreed 2026-10-08; nothing built yet. This is the spec for a fresh
Claude Code session on the work PC. Read `../CLAUDE.md` first — it describes the V2
codebase whose rules V3 must carry over.

---

## 1. Why V3

V2 (`tiledo.py`: PyQt5, local JSON files) is a personal tool. V3 turns it into a
small team tool:

- the owner (manager) assigns engineering/drafting tasks to a couple of people and
  sees their progress from one place;
- members add and manage their own tasks in a reduced view that the owner oversees;
- it works on the owner's iPhone as well as on PCs;
- it replaces a shared Excel sheet, so the bar is low but reliability matters.

## 2. Decisions already made

| Topic | Decision | Why |
|---|---|---|
| Platform | Web app installable as a PWA; one codebase serves manager and member views | Multi-user needs a shared backend anyway; zero install for members; phone access |
| Backend | Firebase: Firestore + Firebase Auth + Firebase Hosting | Owner is fluent with Firebase; realtime sync for free; free tier covers the team |
| Team | 2–3 members now; design for ≤ 10, don't over-engineer | |
| Member view | Reduced: their tasks plus project context; can add/manage their own; owner sees everything | |
| Desktop app | V2 stays as-is (v2.2.x bug fixes only); no new PyQt5 features | Avoid building things twice |
| Repo | Same repo `p-scott-0/tiledo`, V3 under `web/`; work GitHub account (company design email) added as a **collaborator** — no fork | One history, no PRs-to-self |
| Where built | On the work PC with Claude desktop; memory from the home PC is **not** available there — this repo is the only context | |
| Desktop niceties | PWA install + "start at login"; global capture hotkey via a 10-line AHK script that opens the capture URL; system tray not replicated | |

## 3. Scope

### V3.0 — must have
- Auth (Google sign-in restricted to the company domain if they use Google Workspace,
  otherwise email-link), `users` collection with role `owner` | `member`.
- Projects (root tasks) → task tree of arbitrary depth (as V2), priority, stage,
  waiting/blocked pairing, plain-text notes.
- Assignment: `assignee` per task; **My tasks** view for members; manager board =
  V2's focus grid (priority sections; in-progress → other → blocked ordering;
  "+N queued" chip).
- Progress: stage changes, completion, and an **activity log** per task
  (who / what / when).
- The V2.2 interaction rules (section 6): list/tile toggle per parent, drag-and-drop
  with a gap placeholder, right-click menu, Enter saves dialogs, completed strip
  capped with "show all", archive from within a task.
- Quick capture: in-app shortcut; on PC an AHK hotkey opens
  `/capture?parent=<last-open-task>`.
- Archive + restore (flag, not a separate store).
- One-off import of V2 `data.json` + `archive.json`.
- Mobile layout (iPhone Safari PWA): list rows by default on narrow screens, actions
  in a bottom sheet, floating add button.

### V3.1 — later
Comments on tasks, push notifications (FCM) on assignment, templates, recurring
checklists, rich-text notes pages (import V2 `notes.json`), offline write queue.

### Out of scope
Time tracking, Gantt/scheduling, file attachments beyond pasted images, permissions
finer than owner/member, multi-tenant.

## 4. Data model (Firestore)

```
users/{uid}            { name, email, role: "owner"|"member", createdAt }

tasks/{taskId}         { title, notes,
                         priority: "high"|"medium"|"low",
                         stage: <stageId>,
                         parentId: <taskId>|null,
                         order: number,            // sparse, steps of 10 (as V2)
                         completed: bool,
                         assignee: <uid>|null,
                         createdBy: <uid>, createdAt, updatedAt,
                         waiting: { note, since, prevStage } | null,
                         view: "tiles"|"list",
                         archivedAt: timestamp|null }

tasks/{taskId}/activity/{id}
                       { at, by: <uid>,
                         type: "create"|"edit"|"stage"|"complete"|"assign"|"archive",
                         from, to }

config/stages          { list: [ { id, name, color } ] }   // owner-editable, V2 semantics
config/templates       { list: [...] }                     // V3.1
```

Notes:
- Keep **one flat `tasks` collection with `parentId`**, exactly like V2. A small
  team's whole open set fits in memory, so the client subscribes once
  (`onSnapshot` on `archivedAt == null`) and all tree logic runs client-side. The
  V2 helpers port one-to-one: `children_of`, `descendant_ids`, `ancestor_chain`,
  `bucket`, `insert_relative`, `nest_under`, `renumber`, `stage_ranker`,
  `set_waiting`, `clear_waiting`.
- Archive is `archivedAt` set on the root plus its subtree (same cascade as V2's
  `archive_task`), not a separate file.
- Stages stay user-editable; find the semantic ones by stock id then by name
  (`blocked`, `in_progress`) as V2 does — never hard-code ids elsewhere.
- **Security rules are the enforcement boundary**, not the UI:
  - members: read all tasks and users; create tasks; update tasks they created or
    are assigned to; no writes to `config/*` or other users' docs;
  - owner: everything. Bootstrap the owner by hard-coding the owner uid in the rules
    (or a one-time `config/owners` doc) before anyone else signs in.

## 5. Views

**Owner**
- Board (root): priority sections; cards show assignee initials, stage chip, waiting
  reason as subtext, progress bar at the foot of the card.
- Drill-in with breadcrumb; list/tile toggle; completed strip (4 rows + show all,
  per-row and bulk archive).
- People: one column per member — open tasks ordered like the board, last activity.
- Activity feed: last ~50 events across all tasks.

**Member**
- My tasks: assigned to me, grouped by project, board ordering.
- Project view: read everything; edit own/assigned; add task (assignee defaults to me,
  parent defaults to the open task).

**Shared**: search (Ctrl+F), single-level undo of your own last action (or rely on the
activity log — don't rebuild V2's 30-deep snapshot stack).

**Mobile**: same routes; below ~700 px switch to list rows, actions in a sheet,
quick add as a floating button.

## 6. UX rules carried over from V2.2 — do not regress

1. Waiting and Blocked are one thing: setting a wait moves the task to Blocked and
   remembers the previous stage; clearing it restores; leaving Blocked clears the
   wait; choosing Blocked asks for a reason (optional).
2. Right-click on a card opens the same menu as the ⋯ button.
3. Enter saves a dialog; Esc cancels; destructive confirms default to Cancel.
4. Within a priority section: in-progress cards first, everything else next,
   blocked/waiting last; manual order within each group.
5. Live re-sort on every change; new tasks land after the open ones, before blocked.
6. A parent can show its children as tiles or as a compact bullet-style list
   (per-task setting, remembered).
7. Quick capture defaults to the currently open (or last opened) task, with a
   picker to choose another target.
8. Dragging lifts the card out and opens a gap where it would land (iOS home-screen
   feel); dropping in blank space lands after the last card.
9. Blocked/waiting cards show the reason as their subtext.
10. Progress bar sits at the bottom of the card so subtext has room.
11. Completed children are capped (4) with "Show all".
12. Completed children can be archived from within the parent (one or all).

## 7. Tech choices (recommendation, not mandate)

- **Vite + vanilla ES modules (TypeScript optional)**, Firebase JS SDK v10 modular,
  `vite-plugin-pwa` for the manifest/service worker. The owner's other projects are
  single-file vanilla HTML, so this stays familiar; add Preact only if state wiring
  gets painful.
- Realtime: one `onSnapshot` listener per signed-in user on open tasks; derive every
  view from that array (mirrors V2's `data["tasks"]`).
- Hosting: Firebase Hosting, deployed from GitHub Actions on push to `main`
  (`web-deploy.yml`, service-account secret). Keep the existing `build.yml` for the
  exe untouched.
- Theme: port the V2 tokens — `BG #16181a`, `NAV #111315`, `SURF #1f2225`,
  `SURF2 #191c1e`, `BDR #2e3236`, `TEXT #d0d4d8`, `DIM #7a8088`, `ACC #e8982a`,
  `GRN #4caa5c`, `RED #cc4444`; uppercase 7pt micro-labels; 3 px priority stripe.

## 8. Migration from V2

`web/tools/import_v2.py` (Firebase Admin SDK, run once from the owner's PC):
read `~/.tiledo/data.json` and `archive.json`; map fields as-is (`stage`, `order`,
`waiting` → `{note, since, prevStage}`, `archived_at` → `archivedAt`,
`view` → `view`); `assignee = createdBy = owner uid`; write stages to
`config/stages`. Non-destructive — keep V2 running until V3 is trusted, then stop
using V2 for tasks (notes stay in V2 until V3.1).

## 9. Setup checklist (work PC)

1. **GitHub:** on `p-scott-0/tiledo` → Settings → Collaborators → add the work
   account. Clone on the work PC with that account's credentials; in that clone set
   `git config user.email <company design email>`.
2. **Firebase console:** create project (e.g. `tiledo-team`); enable Authentication
   (Google and/or Email link), Firestore (production mode; rules from
   `web/firestore.rules`), Hosting. Add a web app and paste its config into
   `web/src/firebase-config.js` — the config is public by design; safety lives in
   the rules.
3. **Claude desktop at work:** open the repo folder. This file and `CLAUDE.md` are
   the entire context; nothing from the home PC's memory is needed.
4. **Dev loop:** `npm create vite@latest web` (or equivalent), `npm run dev`; test on
   the phone via the PC's LAN IP or a Firebase Hosting preview channel.
5. **CI:** add `.github/workflows/web-deploy.yml` (install → build →
   `firebase deploy --only hosting,firestore:rules`).

## 10. Suggested build order

1. Scaffold + auth + `users` (owner bootstrapped by uid in rules).
2. Firestore model + import script → work with real data from day one.
3. Board + drill-in, porting V2's ordering/drag/dialog rules → the owner can use it
   daily; this is the milestone that lets V2 be retired for tasks.
4. Assignment, My-tasks view, security rules, member sign-in.
5. Activity log + People view.
6. PWA polish, mobile layout, AHK capture hotkey.
7. Cut-over; V3.1 backlog (notes, comments, notifications, recurring).

## 11. Open questions for the owner

- Google Workspace at work? If yes, Google sign-in restricted to the domain is the
  simplest auth; otherwise email-link.
- Do members need the phone layout too, or PC-only for them?
- Recurring checklists in V3.0 or defer (default: defer)?
- Same repo under `web/` (default) or a separate `tiledo-web` repo?
