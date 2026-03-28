# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**patch-review** is a lightweight local code review tool for AI-assisted development workflows. A developer uploads a patch file, adds inline comments in a browser UI, then instructs an AI agent to action those comments — no PR system or editor plugin required.

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

The project is intentionally minimal — **no build step, no database, no bundler**:

- **`review_server.py`** — FastAPI server, serves the UI and manages state in memory
- **`review_ui.html`** — Single HTML file UI (served by the server, no framework)
- **`review.json`** — File-based agent interface; written by the server, read/updated by agents

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/upload` | Accept patch file, parse and store it |
| `GET` | `/diff` | Return parsed diff for rendering |
| `GET` | `/comments` | Return current `review.json` |
| `POST` | `/comments` | Add or update a comment |
| `PATCH` | `/comments/{id}` | Mark resolved/unresolved |

## review.json Schema

```json
{
  "patch_file": "review.patch",
  "generated_at": "2026-03-28T10:00:00",
  "comments": [
    {
      "id": "c1",
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

Agents can optionally add a `resolution_note` field when marking a comment resolved.

## Agent Workflow

When told to "action the review comments":
1. Read `review.patch` to understand what changed
2. Read `review.json` to get comments and line references
3. Action each unresolved comment
4. Set `resolved: true` and `resolved_at` (ISO timestamp) when done

## Input Format

Accepts standard unified diff format from any VCS:

```bash
git diff > review.patch
p4 diff -du > review.patch
svn diff > review.patch
diff -u original.py modified.py > review.patch
```
