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

REVIEWS_DIR = Path("reviews")
HOME_HTML = Path("review_home.html")
UI_HTML = Path("review_ui.html")

# Parsed diff cache keyed by review ID
_diff_cache: dict[str, list] = {}



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



def review_dir(review_id: str) -> Path:
    return REVIEWS_DIR / review_id


def load_review(review_id: str) -> dict:
    path = review_dir(review_id) / "review.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Review not found")
    return json.loads(path.read_text())


def save_review(review_id: str, data: dict) -> None:
    tmp = review_dir(review_id) / "review.json.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(review_dir(review_id) / "review.json")


def get_diff(review_id: str) -> list:
    if review_id not in _diff_cache:
        patch_path = review_dir(review_id) / "review.patch"
        if not patch_path.exists():
            raise HTTPException(status_code=404, detail="Review not found")
        _diff_cache[review_id] = parse_unified_diff(patch_path.read_text())
    return _diff_cache[review_id]



class CommentCreate(BaseModel):
    file: str
    line: int
    line_content: str
    comment: str


class CommentPatch(BaseModel):
    resolved: bool
    resolution_note: Optional[str] = None



@app.get("/", response_class=HTMLResponse)
async def serve_home():
    if not HOME_HTML.exists():
        return HTMLResponse("<h1>review_home.html not found</h1>", status_code=503)
    return HTMLResponse(HOME_HTML.read_text())


@app.get("/reviews", response_model=list)
async def list_reviews():
    if not REVIEWS_DIR.exists():
        return []
    reviews = []
    for d in sorted(REVIEWS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        meta_path = d / "review.json"
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text())
            total = len(data.get("comments", []))
            unresolved = sum(1 for c in data.get("comments", []) if not c.get("resolved"))
            reviews.append({
                "id": d.name,
                "patch_file": data.get("patch_file"),
                "created_at": data.get("created_at"),
                "comment_count": total,
                "unresolved_count": unresolved,
                "url": f"/reviews/{d.name}",
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return reviews



@app.post("/reviews")
async def create_review(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    review_id = uuid.uuid4().hex

    REVIEWS_DIR.mkdir(exist_ok=True)
    review_dir(review_id).mkdir()

    parsed = parse_unified_diff(content)
    _diff_cache[review_id] = parsed

    (review_dir(review_id) / "review.patch").write_text(content)

    review = {
        "patch_file": file.filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "comments": [],
    }
    save_review(review_id, review)

    return {
        "id": review_id,
        "patch_file": file.filename,
        "files": len(parsed),
        "url": f"/reviews/{review_id}",
    }



@app.get("/reviews/{review_id}", response_class=HTMLResponse)
async def serve_review(review_id: str):
    if not (review_dir(review_id) / "review.json").exists():
        raise HTTPException(status_code=404, detail="Review not found")
    if not UI_HTML.exists():
        return HTMLResponse("<h1>review_ui.html not found</h1>", status_code=503)
    return HTMLResponse(UI_HTML.read_text())



@app.get("/reviews/{review_id}/diff")
async def get_review_diff(review_id: str):
    return {"files": get_diff(review_id)}


@app.get("/reviews/{review_id}/comments")
async def get_review_comments(review_id: str):
    return load_review(review_id)


@app.post("/reviews/{review_id}/comments")
async def add_comment(review_id: str, body: CommentCreate):
    review = load_review(review_id)
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
    save_review(review_id, review)
    return comment


@app.patch("/reviews/{review_id}/comments/{comment_id}")
async def patch_comment(review_id: str, comment_id: str, body: CommentPatch):
    review = load_review(review_id)
    for c in review["comments"]:
        if c["id"] == comment_id:
            c["resolved"] = body.resolved
            c["resolved_at"] = datetime.now(timezone.utc).isoformat() if body.resolved else None
            if body.resolution_note is not None:
                c["resolution_note"] = body.resolution_note
            save_review(review_id, review)
            return c
    raise HTTPException(status_code=404, detail="Comment not found")


@app.delete("/reviews/{review_id}/comments/{comment_id}")
async def delete_comment(review_id: str, comment_id: str):
    review = load_review(review_id)
    before = len(review["comments"])
    review["comments"] = [c for c in review["comments"] if c["id"] != comment_id]
    if len(review["comments"]) == before:
        raise HTTPException(status_code=404, detail="Comment not found")
    save_review(review_id, review)
    return {"deleted": comment_id}



def _open_browser():
    import time
    time.sleep(1)
    webbrowser.open("http://localhost:7890")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=7890)
