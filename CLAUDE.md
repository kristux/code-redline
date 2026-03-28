# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**patch-review** is a lightweight local code review tool for AI-assisted development workflows. A developer uploads a patch file, adds inline comments in a browser UI, then instructs an AI agent to action those comments — no PR system or editor plugin required. Reviews support multiple revisions.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

## Running the Tool

```bash
.venv/bin/python review_server.py
# Opens browser at http://localhost:7890
```

## Running Tests

```bash
.venv/bin/pytest tests/test_server.py -v
```

## Architecture

Intentionally minimal — no build step, no database, no bundler:

- **`review_server.py`** — FastAPI server, serves both HTML files, manages review state
- **`review_home.html`** — Homepage listing all reviews (single HTML file, no framework)
- **`review_ui.html`** — Per-review diff UI with inline commenting (single HTML file, no framework)
- **`reviews/{uuid}/`** — One directory per review, containing `r{N}.patch` and `review.json`

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/reviews` | List all reviews |
| `POST` | `/reviews` | Create review (upload patch), returns `{id, url, revision, files}` |
| `GET` | `/reviews/{id}` | Serve review UI |
| `GET` | `/reviews/{id}/diff` | Parsed diff for latest revision |
| `POST` | `/reviews/{id}/revisions` | Upload a new revision patch |
| `GET` | `/reviews/{id}/comments` | Return `review.json` |
| `POST` | `/reviews/{id}/comments` | Add a comment |
| `PATCH` | `/reviews/{id}/comments/{cid}` | Resolve/unresolve a comment |
| `DELETE` | `/reviews/{id}/comments/{cid}` | Delete a comment |

## review.json Schema

```json
{
  "revisions": [
    {"revision": 1, "patch_file": "foo.patch", "created_at": "2026-03-28T10:00:00+00:00"}
  ],
  "comments": [
    {
      "id": "c1a2b3c4",
      "revision": 1,
      "file": "path/to/file.py",
      "line": 45,
      "line_content": "    actual line content here",
      "comment": "reviewer's comment",
      "resolved": false,
      "resolved_at": null
    }
  ]
}
```

`resolution_note` is an optional field agents can add when marking a comment resolved.

## Agent Workflow

When told to "action the review comments":
1. Read `reviews/{id}/review.json` to get unresolved comments
2. Read `reviews/{id}/r{N}.patch` (latest revision) to understand what changed
3. Action each unresolved comment
4. Set `resolved: true` and `resolved_at` (ISO timestamp) when done
5. Upload a new revision: `POST /reviews/{id}/revisions` with the updated full diff

## Revision Convention

Every revision upload must be a **full diff from the base branch**, not an incremental diff from the previous revision:

```bash
git diff main > review.patch        # correct
git diff HEAD > review.patch        # wrong — only shows last commit
```

This ensures `GET /reviews/{id}/diff` always shows the complete picture of what changed.
