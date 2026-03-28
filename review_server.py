import json
import re
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="patch-review")

REVIEW_JSON = Path("review.json")
UI_HTML = Path("review_ui.html")

# In-memory state for the current diff session
_state = {
    "parsed_diff": None,
    "patch_filename": None,
}


# --- Diff parsing ---

def parse_unified_diff(content: str) -> list:
    files = []
    current_file = None
    current_hunk = None
    old_num = 0
    new_num = 0

    for line in content.splitlines():
        if line.startswith("--- "):
            if current_file is not None:
                files.append(current_file)
            old_path = line[4:].split("\t")[0].strip()
            if old_path.startswith("a/"):
                old_path = old_path[2:]
            current_file = {"old_file": old_path, "new_file": None, "hunks": []}
            current_hunk = None

        elif line.startswith("+++ ") and current_file is not None:
            new_path = line[4:].split("\t")[0].strip()
            if new_path.startswith("b/"):
                new_path = new_path[2:]
            current_file["new_file"] = new_path

        elif line.startswith("@@ ") and current_file is not None:
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                old_num = int(m.group(1))
                new_num = int(m.group(2))
                current_hunk = {"header": line, "lines": []}
                current_file["hunks"].append(current_hunk)

        elif current_hunk is not None:
            if line.startswith("+"):
                current_hunk["lines"].append(
                    {"type": "added", "content": line[1:], "old_line": None, "new_line": new_num}
                )
                new_num += 1
            elif line.startswith("-"):
                current_hunk["lines"].append(
                    {"type": "removed", "content": line[1:], "old_line": old_num, "new_line": None}
                )
                old_num += 1
            elif line.startswith(" "):
                current_hunk["lines"].append(
                    {"type": "context", "content": line[1:], "old_line": old_num, "new_line": new_num}
                )
                old_num += 1
                new_num += 1
            # "\ No newline at end of file" lines are ignored

    if current_file is not None:
        files.append(current_file)

    return files


# --- review.json helpers ---

def load_review() -> dict:
    if REVIEW_JSON.exists():
        return json.loads(REVIEW_JSON.read_text())
    return {"patch_file": None, "generated_at": None, "comments": []}


def save_review(data: dict) -> None:
    REVIEW_JSON.write_text(json.dumps(data, indent=2))


# --- Pydantic models ---

class CommentCreate(BaseModel):
    file: str
    line: int
    line_content: str
    comment: str


class CommentPatch(BaseModel):
    resolved: bool
    resolution_note: Optional[str] = None


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    if not UI_HTML.exists():
        return HTMLResponse("<h1>review_ui.html not found — build it next!</h1>", status_code=503)
    return HTMLResponse(UI_HTML.read_text())


@app.post("/upload")
async def upload_patch(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    _state["parsed_diff"] = parse_unified_diff(content)
    _state["patch_filename"] = file.filename

    review = {
        "patch_file": file.filename,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comments": [],
    }
    save_review(review)
    return {"files": len(_state["parsed_diff"]), "filename": file.filename}


@app.get("/diff")
async def get_diff():
    if _state["parsed_diff"] is None:
        raise HTTPException(status_code=404, detail="No patch loaded")
    return {"files": _state["parsed_diff"]}


@app.get("/comments")
async def get_comments():
    return load_review()


@app.post("/comments")
async def add_comment(body: CommentCreate):
    review = load_review()
    comment = {
        "id": f"c{uuid.uuid4().hex[:8]}",
        "file": body.file,
        "line": body.line,
        "line_content": body.line_content,
        "comment": body.comment,
        "resolved": False,
        "resolved_at": None,
    }
    review["comments"].append(comment)
    save_review(review)
    return comment


@app.patch("/comments/{comment_id}")
async def patch_comment(comment_id: str, body: CommentPatch):
    review = load_review()
    for c in review["comments"]:
        if c["id"] == comment_id:
            c["resolved"] = body.resolved
            c["resolved_at"] = datetime.now(timezone.utc).isoformat() if body.resolved else None
            if body.resolution_note is not None:
                c["resolution_note"] = body.resolution_note
            save_review(review)
            return c
    raise HTTPException(status_code=404, detail="Comment not found")


# --- Entrypoint ---

def _open_browser():
    import time
    time.sleep(1)
    webbrowser.open("http://localhost:7890")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=7890)
