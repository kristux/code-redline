# patch-review

A lightweight local code review tool for AI-assisted development workflows.

Upload a patch file, add inline comments in the browser, and let your AI agent
action them — no PR system, no editor plugin, no VCS lock-in.

## The problem

AI agents write code fast. Reviewing it shouldn't require spinning up a formal
review in Swarm, GitHub, or similar. This tool gives you the discipline of
line-level code review with none of the overhead.

## How it works

```
# Agent creates the review
curl -X POST http://localhost:7890/reviews -F "file=@review.patch"
# → {"id": "abc123", "url": "/reviews/abc123", ...}

# Developer opens the URL, adds inline comments in the browser

# Agent reads review.json, actions the comments, uploads a new revision
curl -X POST http://localhost:7890/reviews/abc123/revisions -F "file=@review.patch"

# Developer refreshes to see what's resolved
```

## Revision convention

Each revision should be a **full diff from the base branch**, not an incremental
diff from the previous revision. This ensures the review always shows the complete
picture of what changed.

```bash
git diff main > review.patch        # correct — full diff from base
git diff HEAD > review.patch        # wrong — only shows last commit
```

The same applies to subsequent revisions after the agent addresses comments:

```bash
# After agent makes changes:
git diff main > review.patch
curl -X POST http://localhost:7890/reviews/abc123/revisions -F "file=@review.patch"
```

## VCS compatibility

Any tool that produces a unified diff works:

| VCS | Command |
|-----|---------|
| Git | `git diff main > review.patch` |
| Perforce | `p4 diff -du > review.patch` |
| SVN | `svn diff > review.patch` |
| Generic | `diff -u original.py modified.py > review.patch` |

## Agent integration

After actioning comments, the agent updates `review.json` directly:

- Set `resolved: true` and `resolved_at` (ISO timestamp) on each addressed comment
- Optionally add `resolution_note` explaining what was changed
- Upload a new revision patch so the developer can see the updated diff

No MCP server, no special tooling. Just files and a REST API.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python review_server.py
```

## License

MIT
