"""Community posts: stored-XSS defences, approval state machine, rating rules."""
import pytest

XSS = '<p>hi</p><script>alert(1)</script><img src=x onerror="alert(2)"><a href="javascript:alert(3)">l</a>'


def _create(client, **overrides):
	data = {"title": "XSS Post", "description": XSS, "content_type": "Text/Article", "category": "General", "status": "PUBLISHED"}
	data.update(overrides)
	return client.post("/community/create", data=data)


def test_post_bodies_are_sanitised_on_create_and_edit(moderator, world, db):
	_create(moderator)
	post = db("SELECT id, description FROM posts WHERE title = 'XSS Post'")[0]
	assert "<script" not in post["description"] and "onerror" not in post["description"] and "javascript:" not in post["description"]
	assert "<p>hi</p>" in post["description"]
	moderator.post(f"/community/edit/{post['id']}", data={"title": "XSS Post", "description": "<b>x</b><script>y()</script>", "content_type": "Text/Article", "category": "General", "status": "PUBLISHED"})
	assert db("SELECT description FROM posts WHERE id = ?", (post["id"],))[0]["description"] == "<b>x</b>"


def test_api_post_bodies_are_sanitised(anon, world, db):
	response = anon.post("/api/v1/posts", json={"title": "API XSS", "description": XSS, "content_type": "Text/Article"}, headers=world.api_keys["mod"])
	assert response.status_code == 201, response.get_json()
	assert "<script" not in db("SELECT description FROM posts WHERE title = 'API XSS'")[0]["description"]


def test_legacy_unsanitised_bodies_are_cleaned_when_rendered(student, moderator, world, db):
	db("UPDATE posts SET description = ? WHERE id = ?", (XSS, world.published_post_id))
	for page in (student.get("/community"), student.get(f"/community/post/{world.published_post_id}")):
		assert page.status_code == 200
		body = page.get_data(as_text=True)
		assert "alert(1)" not in body and "onerror" not in body
	db("UPDATE posts SET description = ? WHERE id = ?", (XSS, world.pending_post_id))
	queue = moderator.get("/community/approval-queue").get_data(as_text=True)
	assert "alert(1)" not in queue and "onerror" not in queue


def test_notification_text_is_escaped_in_the_header_script():
	from pathlib import Path

	import app as app_module

	html = Path(app_module.__file__).resolve().parent.joinpath("templates", "base.html").read_text(encoding="utf-8")
	assert "${n.message}" not in html, "notification messages must be escaped before innerHTML"


def test_only_pending_or_unpublished_posts_can_be_reviewed(moderator, world, db):
	# a published post by someone else cannot be "reviewed" again
	published = db("INSERT INTO posts (title, description, content_type, category, created_by, status, version_number) VALUES ('Live', '<p>x</p>', 'Text/Article', 'General', ?, 'PUBLISHED', 1) RETURNING id", (world.users["student"],))[0]["id"]
	response = moderator.post(f"/community/approval-queue/{published}/action", data={"action": "REJECT", "comments": "late"}, follow_redirects=True)
	assert b"not awaiting review" in response.data
	assert db("SELECT status FROM posts WHERE id = ?", (published,))[0]["status"] == "PUBLISHED"
	# maya's pending post (author is 'student') can be approved by the moderator
	assert moderator.post(f"/community/approval-queue/{world.pending_post_id}/action", data={"action": "APPROVE", "comments": ""}).status_code == 302
	assert db("SELECT status FROM posts WHERE id = ?", (world.pending_post_id,))[0]["status"] == "PUBLISHED"


def test_only_published_posts_can_be_rated(moderator, anon, world, db):
	response = moderator.post(f"/community/post/{world.draft_post_id}/rate", data={"rating": "5"}, follow_redirects=True)
	assert b"Only published posts can be rated" in response.data
	assert not db("SELECT 1 FROM post_ratings WHERE post_id = ?", (world.draft_post_id,))
	api = anon.post(f"/api/v1/posts/{world.draft_post_id}/rate", json={"rating": 5}, headers=world.api_keys["mod"])
	assert api.status_code == 400
	assert anon.post(f"/api/v1/posts/{world.published_post_id}/rate", json={"rating": "five"}, headers=world.api_keys["student"]).status_code == 400
	assert anon.post(f"/api/v1/posts/{world.published_post_id}/rate", json={"rating": 4}, headers=world.api_keys["student"]).status_code in (200, 201)
