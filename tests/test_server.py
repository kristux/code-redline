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
    """Isolate reviews directory and reset in-memory cache between tests."""
    monkeypatch.setattr(review_server, "REVIEWS_DIR", tmp_path / "reviews")
    review_server._diff_cache.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def review(client):
    """Create a review, return (client, review_id)."""
    r = client.post("/reviews", files={"file": ("test.patch", TEST_PATCH, "text/plain")})
    assert r.status_code == 200
    return client, r.json()["id"]


# --- POST /reviews ---

def test_create_review_returns_id_and_url(client):
    r = client.post("/reviews", files={"file": ("my.patch", TEST_PATCH, "text/plain")})
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["url"] == f"/reviews/{data['id']}"
    assert data["files"] == 2
    assert data["patch_file"] == "my.patch"


def test_create_review_persists_to_disk(client, tmp_path, monkeypatch):
    reviews_dir = tmp_path / "reviews"
    monkeypatch.setattr(review_server, "REVIEWS_DIR", reviews_dir)
    r = client.post("/reviews", files={"file": ("my.patch", TEST_PATCH, "text/plain")})
    rid = r.json()["id"]
    assert (reviews_dir / rid / "review.patch").exists()
    assert (reviews_dir / rid / "review.json").exists()


# --- GET /reviews ---

def test_list_reviews_empty(client):
    assert client.get("/reviews").json() == []


def test_list_reviews_shows_created(client):
    client.post("/reviews", files={"file": ("a.patch", TEST_PATCH, "text/plain")})
    client.post("/reviews", files={"file": ("b.patch", TEST_PATCH, "text/plain")})
    reviews = client.get("/reviews").json()
    assert len(reviews) == 2
    names = {rv["patch_file"] for rv in reviews}
    assert names == {"a.patch", "b.patch"}


def test_list_reviews_includes_comment_counts(review):
    client, rid = review
    client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    })
    rv = next(r for r in client.get("/reviews").json() if r["id"] == rid)
    assert rv["comment_count"] == 1
    assert rv["unresolved_count"] == 1


# --- GET /reviews/{id}/diff ---

def test_diff_returns_two_files(review):
    client, rid = review
    files = client.get(f"/reviews/{rid}/diff").json()["files"]
    assert len(files) == 2
    assert files[0]["new_file"] == "foo.py"
    assert files[1]["new_file"] == "bar.py"


def test_diff_unknown_review_returns_404(client):
    assert client.get("/reviews/doesnotexist/diff").status_code == 404


def test_diff_line_types(review):
    client, rid = review
    lines = client.get(f"/reviews/{rid}/diff").json()["files"][0]["hunks"][0]["lines"]
    types = {l["type"] for l in lines}
    assert {"context", "added", "removed"} == types


def test_diff_line_numbers(review):
    client, rid = review
    lines = client.get(f"/reviews/{rid}/diff").json()["files"][0]["hunks"][0]["lines"]
    context = next(l for l in lines if l["type"] == "context")
    assert context["old_line"] is not None and context["new_line"] is not None
    added = next(l for l in lines if l["type"] == "added")
    assert added["old_line"] is None and added["new_line"] is not None
    removed = next(l for l in lines if l["type"] == "removed")
    assert removed["old_line"] is not None and removed["new_line"] is None


# --- GET/POST /reviews/{id}/comments ---

def test_get_comments_empty(review):
    client, rid = review
    data = client.get(f"/reviews/{rid}/comments").json()
    assert data["comments"] == []


def test_add_comment_returns_comment(review):
    client, rid = review
    r = client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2,
        "line_content": '    print("hello world")',
        "comment": "use a logger",
    })
    assert r.status_code == 200
    c = r.json()
    assert c["file"] == "foo.py"
    assert c["line"] == 2
    assert c["resolved"] is False
    assert c["id"].startswith("c")


def test_add_comment_persists(review):
    client, rid = review
    client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix this"
    })
    comments = client.get(f"/reviews/{rid}/comments").json()["comments"]
    assert len(comments) == 1
    assert comments[0]["comment"] == "fix this"


def test_multiple_comments_accumulate(review):
    client, rid = review
    for i in range(3):
        client.post(f"/reviews/{rid}/comments", json={
            "file": "foo.py", "line": i + 1, "line_content": "x", "comment": f"comment {i}"
        })
    assert len(client.get(f"/reviews/{rid}/comments").json()["comments"]) == 3


# --- PATCH /reviews/{id}/comments/{cid} ---

def test_resolve_comment(review):
    client, rid = review
    cid = client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    }).json()["id"]

    r = client.patch(f"/reviews/{rid}/comments/{cid}", json={"resolved": True})
    assert r.status_code == 200
    assert r.json()["resolved"] is True
    assert r.json()["resolved_at"] is not None


def test_unresolve_comment(review):
    client, rid = review
    cid = client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    }).json()["id"]
    client.patch(f"/reviews/{rid}/comments/{cid}", json={"resolved": True})
    r = client.patch(f"/reviews/{rid}/comments/{cid}", json={"resolved": False})
    assert r.json()["resolved"] is False
    assert r.json()["resolved_at"] is None


def test_resolve_with_resolution_note(review):
    client, rid = review
    cid = client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "fix"
    }).json()["id"]
    r = client.patch(f"/reviews/{rid}/comments/{cid}", json={
        "resolved": True, "resolution_note": "switched to logging.info"
    })
    assert r.json()["resolution_note"] == "switched to logging.info"


def test_patch_unknown_comment_returns_404(review):
    client, rid = review
    assert client.patch(f"/reviews/{rid}/comments/nope", json={"resolved": True}).status_code == 404


# --- DELETE /reviews/{id}/comments/{cid} ---

def test_delete_comment(review):
    client, rid = review
    cid = client.post(f"/reviews/{rid}/comments", json={
        "file": "foo.py", "line": 2, "line_content": "x", "comment": "remove me"
    }).json()["id"]

    r = client.delete(f"/reviews/{rid}/comments/{cid}")
    assert r.status_code == 200
    assert r.json() == {"deleted": cid}
    assert all(c["id"] != cid for c in client.get(f"/reviews/{rid}/comments").json()["comments"])


def test_delete_unknown_comment_returns_404(review):
    client, rid = review
    assert client.delete(f"/reviews/{rid}/comments/nope").status_code == 404
