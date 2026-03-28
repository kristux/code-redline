import json
import pytest
from fastapi.testclient import TestClient

import review_server
from review_server import app

TEST_PATCH = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def hello():
-    print("hello")
+    print("hello world")
+    return True

--- a/bar.py
+++ b/bar.py
@@ -10,4 +10,3 @@
 class Bar:
-    x = 1
-    y = 2
+    x = 2

"""


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """Isolate review.json and reset in-memory state between tests."""
    monkeypatch.setattr(review_server, "REVIEW_JSON", tmp_path / "review.json")
    review_server._state["parsed_diff"] = None
    review_server._state["patch_filename"] = None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def loaded(client):
    """Client with TEST_PATCH already uploaded."""
    client.post("/upload", files={"file": ("test.patch", TEST_PATCH, "text/plain")})
    return client


# --- /upload ---

def test_upload_returns_file_count_and_name(client):
    r = client.post("/upload", files={"file": ("my.patch", TEST_PATCH, "text/plain")})
    assert r.status_code == 200
    assert r.json() == {"files": 2, "filename": "my.patch"}


def test_upload_resets_comments(loaded):
    loaded.post("/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "old comment"
    })
    loaded.post("/upload", files={"file": ("test.patch", TEST_PATCH, "text/plain")})
    assert loaded.get("/comments").json()["comments"] == []


# --- /diff ---

def test_diff_before_upload_returns_404(client):
    assert client.get("/diff").status_code == 404


def test_diff_returns_two_files(loaded):
    files = loaded.get("/diff").json()["files"]
    assert len(files) == 2
    assert files[0]["new_file"] == "foo.py"
    assert files[1]["new_file"] == "bar.py"


def test_diff_line_types(loaded):
    lines = loaded.get("/diff").json()["files"][0]["hunks"][0]["lines"]
    types = [l["type"] for l in lines]
    assert "context" in types
    assert "added" in types
    assert "removed" in types


def test_diff_line_numbers(loaded):
    lines = loaded.get("/diff").json()["files"][0]["hunks"][0]["lines"]
    # context line: has both old and new line numbers
    context = next(l for l in lines if l["type"] == "context")
    assert context["old_line"] is not None
    assert context["new_line"] is not None
    # added line: only new_line
    added = next(l for l in lines if l["type"] == "added")
    assert added["old_line"] is None
    assert added["new_line"] is not None
    # removed line: only old_line
    removed = next(l for l in lines if l["type"] == "removed")
    assert removed["old_line"] is not None
    assert removed["new_line"] is None


# --- /comments POST ---

def test_add_comment_returns_comment(loaded):
    r = loaded.post("/comments", json={
        "file": "foo.py", "line": 2,
        "line_content": '    print("hello world")',
        "comment": "use a logger",
    })
    assert r.status_code == 200
    c = r.json()
    assert c["file"] == "foo.py"
    assert c["line"] == 2
    assert c["comment"] == "use a logger"
    assert c["resolved"] is False
    assert c["resolved_at"] is None
    assert c["id"].startswith("c")


def test_add_comment_persists_to_review_json(loaded):
    loaded.post("/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix this"
    })
    comments = loaded.get("/comments").json()["comments"]
    assert len(comments) == 1
    assert comments[0]["comment"] == "fix this"


def test_multiple_comments_accumulate(loaded):
    for i in range(3):
        loaded.post("/comments", json={
            "file": "foo.py", "line": i + 1, "line_content": "x", "comment": f"comment {i}"
        })
    assert len(loaded.get("/comments").json()["comments"]) == 3


# --- /comments/{id} PATCH ---

def test_resolve_comment(loaded):
    comment_id = loaded.post("/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    }).json()["id"]

    r = loaded.patch(f"/comments/{comment_id}", json={"resolved": True})
    assert r.status_code == 200
    c = r.json()
    assert c["resolved"] is True
    assert c["resolved_at"] is not None


def test_unresolve_comment(loaded):
    comment_id = loaded.post("/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    }).json()["id"]
    loaded.patch(f"/comments/{comment_id}", json={"resolved": True})

    r = loaded.patch(f"/comments/{comment_id}", json={"resolved": False})
    assert r.json()["resolved"] is False
    assert r.json()["resolved_at"] is None


def test_resolve_with_resolution_note(loaded):
    comment_id = loaded.post("/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    }).json()["id"]

    r = loaded.patch(f"/comments/{comment_id}", json={
        "resolved": True, "resolution_note": "switched to logging.info"
    })
    assert r.json()["resolution_note"] == "switched to logging.info"


def test_patch_unknown_comment_returns_404(loaded):
    r = loaded.patch("/comments/doesnotexist", json={"resolved": True})
    assert r.status_code == 404


# --- /comments/{id} DELETE ---

def test_delete_comment(loaded):
    comment_id = loaded.post("/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "remove me"
    }).json()["id"]

    r = loaded.delete(f"/comments/{comment_id}")
    assert r.status_code == 200
    assert r.json() == {"deleted": comment_id}
    assert all(c["id"] != comment_id for c in loaded.get("/comments").json()["comments"])


def test_delete_unknown_comment_returns_404(loaded):
    assert loaded.delete("/comments/doesnotexist").status_code == 404
