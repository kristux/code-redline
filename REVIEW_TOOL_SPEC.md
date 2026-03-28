# Local Code Review Tool — Project Spec

## Goal

A lightweight local web server that provides a code review workflow for AI-assisted
development. The developer uploads a patch/diff file, adds inline comments via a
browser UI, and the AI agent reads those comments and actions them — without any
dependency on a hosted VCS, PR system, or editor plugin.

---

## Problem Statement

AI-generated code lacks a structured review loop. Formal review tools (Swarm, GitHub
PRs) require too much overhead for solo or small-team AI-assisted workflows. This tool
closes that gap with a minimal, file-based approach that any AI agent can consume.

---

## Core Principles

- **File-based integration** — agent interaction is via plain JSON, no API calls needed
- **VCS agnostic** — accepts any unified diff/patch file (Perforce, Git, SVN, raw diff)
- **Zero dependencies on editor or platform** — runs in any browser
- **Lightweight** — single Python file for the server, single HTML file for the UI

---

## Patch File Format

Accept standard unified diff format, which all major VCS can generate:

```bash
# Git
git diff > review.patch

# Perforce
p4 diff -du > review.patch

# Generic
diff -u original.py modified.py > review.patch
```

---

## Workflow

```
1. Developer runs:  python review_server.py
2. Browser opens automatically at http://localhost:7890
3. Developer uploads a .patch or .diff file
4. Diff renders in the browser with line-level comment capability
5. Developer clicks lines and adds comments
6. Comments are saved to review.json in the same folder
7. Developer tells Claude Code: "action the review comments in review.json"
8. Claude reads the patch + JSON, makes changes, marks comments resolved
9. Developer refreshes browser to see resolved/remaining comments
```

---

## Components

### `review_server.py`
- FastAPI or Flask server
- Serves the UI
- Endpoints:
  - `POST /upload` — accepts patch file, parses and stores it
  - `GET /diff` — returns parsed diff for rendering
  - `GET /comments` — returns current review.json
  - `POST /comments` — adds or updates a comment
  - `PATCH /comments/{id}` — mark resolved/unresolved

### `review_ui.html` (served by the server)
- Single HTML file, no build step
- Unified or split diff view (toggle between both)
- Click any line → inline comment input appears
- Comments shown inline with the diff
- Resolved comments visually distinct (greyed out, strikethrough)
- Comment panel on the side showing all comments and their status

### `review.json` (the agent interface)
```json
{
  "patch_file": "review.patch",
  "generated_at": "2026-03-28T10:00:00",
  "comments": [
    {
      "id": "c1",
      "file": "distribution/coordinator.py",
      "line": 45,
      "line_content": "    type_id = getattr(item, 'typeID', None)",
      "comment": "Too defensive — use item.typeID directly and let it raise",
      "resolved": false,
      "resolved_at": null
    }
  ]
}
```

---

## AI Agent Integration

The agent needs no special tooling. Workflow from the agent side:

1. Read `review.patch` to understand what changed
2. Read `review.json` to get comments and which lines they refer to
3. Action each unresolved comment
4. Set `resolved: true` and `resolved_at` timestamp when done
5. Optionally add a `resolution_note` field explaining what was changed

The developer refreshes the browser to see updated state.

---

## UI Behaviour

- Diff lines are colour coded (added/removed/context) in standard style
- Line numbers are clickable
- Clicking a line number opens an inline comment box
- Existing comments shown below their line
- Top bar shows: filename, comment count, unresolved count
- "Clear all resolved" button to tidy up
- Auto-opens browser on server start

---

## Non-Goals (for now)

- No authentication (local only)
- No multi-user support
- No git/p4 integration beyond accepting the patch file
- No syntax highlighting (nice to have later)
- No persisting multiple reviews (one active review at a time)

---

## Future Ideas

- Syntax highlighting via highlight.js
- Claude Code CLAUDE.md snippet auto-generation from comments
  (e.g. "add this as a style rule" button)
- Review history / archive
- Direct p4/git diff generation from the UI
- MCP server wrapper if agent-initiated reviews become useful
