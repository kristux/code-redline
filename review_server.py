import difflib
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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="code-redline")
app.mount("/static", StaticFiles(directory="static"), name="static")

REVIEWS_DIR = Path("reviews")
HOME_HTML = Path("review_home.html")
UI_HTML = Path("review_ui.html")
INFO_HTML = Path("info.html")

# Parsed diff cache keyed by review ID (always the latest revision)
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

    if current_file is not None:
        files.append(current_file)

    return files


def compute_interdiff(patch1: str, patch2: str) -> list:
    def extract_new_state(parsed_files: list, filename: str) -> list[str]:
        for f in parsed_files:
            if (f["new_file"] == filename) or (f["old_file"] == filename):
                return [ln["content"] for hunk in f["hunks"]
                        for ln in hunk["lines"] if ln["type"] in ("context", "added")]
        return []

    files1 = parse_unified_diff(patch1)
    files2 = parse_unified_diff(patch2)
    names = sorted({f["new_file"] or f["old_file"] for f in files1} |
                   {f["new_file"] or f["old_file"] for f in files2})

    diff_parts = []
    for name in names:
        a = extract_new_state(files1, name)
        b = extract_new_state(files2, name)
        if a == b:
            continue
        diff = list(difflib.unified_diff(
            [l + "\n" for l in a], [l + "\n" for l in b],
            fromfile=f"a/{name}", tofile=f"b/{name}", lineterm="",
        ))
        if diff:
            diff_parts.append("\n".join(diff))

    return parse_unified_diff("\n".join(diff_parts)) if diff_parts else []


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
        review = load_review(review_id)
        revision = len(review["revisions"])
        patch_path = review_dir(review_id) / f"r{revision}.patch"
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


@app.get("/info", response_class=HTMLResponse)
async def serve_info():
    if not INFO_HTML.exists():
        return HTMLResponse("<h1>info.html not found</h1>", status_code=503)
    return HTMLResponse(INFO_HTML.read_text())


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
            revisions = data.get("revisions", [])
            latest = revisions[-1] if revisions else {}
            total = len(data.get("comments", []))
            unresolved = sum(1 for c in data.get("comments", []) if not c.get("resolved"))
            reviews.append({
                "id": d.name,
                "patch_file": latest.get("patch_file"),
                "created_at": revisions[0].get("created_at") if revisions else None,
                "revision_count": len(revisions),
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

    (review_dir(review_id) / "r1.patch").write_text(content)

    review = {
        "revisions": [
            {
                "revision": 1,
                "patch_file": file.filename,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "comments": [],
    }
    save_review(review_id, review)

    return {
        "id": review_id,
        "revision": 1,
        "patch_file": file.filename,
        "files": len(parsed),
        "url": f"/reviews/{review_id}",
    }


@app.post("/reviews/{review_id}/revisions")
async def add_revision(review_id: str, file: UploadFile = File(...)):
    review = load_review(review_id)
    content = (await file.read()).decode("utf-8", errors="replace")
    revision = len(review["revisions"]) + 1

    (review_dir(review_id) / f"r{revision}.patch").write_text(content)

    parsed = parse_unified_diff(content)
    _diff_cache[review_id] = parsed

    review["revisions"].append({
        "revision": revision,
        "patch_file": file.filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    save_review(review_id, review)

    return {
        "id": review_id,
        "revision": revision,
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
async def get_review_diff(
    review_id: str,
    from_revision: Optional[int] = None,
    to_revision: Optional[int] = None,
):
    review = load_review(review_id)
    total = len(review["revisions"])

    if from_revision is None and to_revision is None:
        return {"files": get_diff(review_id), "mode": "full"}

    if from_revision is None or to_revision is None:
        raise HTTPException(status_code=400, detail="Provide both from_revision and to_revision")
    if not (1 <= from_revision <= total and 1 <= to_revision <= total):
        raise HTTPException(status_code=400, detail="Revision out of range")
    if from_revision == to_revision:
        raise HTTPException(status_code=400, detail="from_revision and to_revision must differ")

    p1 = (review_dir(review_id) / f"r{from_revision}.patch").read_text()
    p2 = (review_dir(review_id) / f"r{to_revision}.patch").read_text()
    return {"files": compute_interdiff(p1, p2), "mode": "interdiff",
            "from_revision": from_revision, "to_revision": to_revision}


@app.get("/reviews/{review_id}/comments")
async def get_review_comments(review_id: str):
    return load_review(review_id)


@app.post("/reviews/{review_id}/comments")
async def add_comment(review_id: str, body: CommentCreate):
    review = load_review(review_id)
    revision = len(review["revisions"])
    comment = {
        "id": f"c{uuid.uuid4().hex[:8]}",
        "revision": revision,
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
