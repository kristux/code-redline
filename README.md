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
p4 diff -du > review.patch       # or git diff, or any unified diff
python review_server.py           # starts server, opens browser
# add inline comments in the UI
# tell your agent: "action the review comments in review.json"
# refresh to see what's resolved
```

## Features

- Accepts any standard unified diff/patch file
- Line-level inline comments
- Comments stored in a plain `review.json` file your agent can read and update
- Resolved/unresolved tracking
- No build step, no database, no accounts

## VCS compatibility

Any tool that produces a unified diff works:

| VCS | Command |
|-----|---------|
| Perforce | `p4 diff -du > review.patch` |
| Git | `git diff > review.patch` |
| SVN | `svn diff > review.patch` |
| Generic | `diff -u original.py modified.py > review.patch` |

## Agent integration

The agent reads two files:

- `review.patch` — to understand what changed
- `review.json` — to get your comments and mark them resolved

No MCP server, no special tooling. Just files.

## Installation

```bash
pip install fastapi uvicorn
python review_server.py
```

## Status

Early development. Contributions welcome.

## License

MIT
