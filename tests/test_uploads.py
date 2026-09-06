"""Uploads must work on a fresh checkout / empty disk: the uploads folder is created on demand (QA-025)."""
import shutil
from io import BytesIO

import app as app_module

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _wipe_upload_folder():
	shutil.rmtree(app_module.UPLOAD_FOLDER, ignore_errors=True)
	assert not app_module.UPLOAD_FOLDER.exists()


def test_profile_picture_upload_creates_the_folder(student, world, db):
	_wipe_upload_folder()
	with student.session_transaction() as sess:
		user_id = sess["user_id"]
	response = student.post("/profile", data={
		"full_name": "Upload Tester", "email": "upload.tester@example.com", "phone_number": "9999999999", "employee_id": "EMP-UPLOAD-TEST",
		"location_id": str(world.location_id), "profile_picture": (BytesIO(PNG), "me.jpg"),
	}, content_type="multipart/form-data")
	assert response.status_code == 302, response.get_data(as_text=True)[:300]
	stored = db("SELECT profile_picture FROM users WHERE id = ?", (user_id,))[0]["profile_picture"]
	assert stored.endswith(".jpg") and (app_module.UPLOAD_FOLDER / stored).is_file(), stored
	with student.session_transaction() as sess:
		assert sess["profile_picture"] == stored


def test_post_thumbnail_and_attachment_upload_create_the_folder(student, db):
	_wipe_upload_folder()
	response = student.post("/community/create", data={
		"title": "Uploads on a fresh disk", "description": "<p>body</p>", "content_type": "Text/Article", "category": "General", "topic_tag": "ops",
		"thumbnail": (BytesIO(PNG), "thumb.png"), "attachments": (BytesIO(b"%PDF-1.4 test"), "notes.pdf"),
	}, content_type="multipart/form-data")
	assert response.status_code == 302, response.get_data(as_text=True)[:300]
	files = sorted(p.name for p in app_module.UPLOAD_FOLDER.iterdir())
	assert any(name.startswith("thumb_") and name.endswith(".png") for name in files), files
	assert any(name.startswith("post_") and name.endswith("_notes.pdf") for name in files), files


def test_upload_path_creates_nested_folders(tmp_path, monkeypatch):
	monkeypatch.setattr(app_module, "UPLOAD_FOLDER", tmp_path / "deep" / "uploads")
	target = app_module.upload_path("thumbs/a.png")
	assert target == tmp_path / "deep" / "uploads" / "thumbs" / "a.png" and target.parent.is_dir()
