"""storage.save_file: the course-upload helper."""
import io

import pytest
from werkzeug.datastructures import FileStorage

import storage


def _upload(name, data=b"%PDF-1.4 test"):
	return FileStorage(stream=io.BytesIO(data), filename=name)


def test_saves_allowed_file_under_a_generated_name(tmp_path):
	folder = tmp_path / "uploads" / "nested"
	saved = storage.save_file(_upload("Course Deck.PPTX"), str(folder))
	assert saved.endswith(".pptx") and len(saved) == 32 + 5, "uuid4 hex + extension"
	assert (folder / saved).read_bytes() == b"%PDF-1.4 test", "folder is created on demand"


@pytest.mark.parametrize("name", ["notes.txt", "script.py", "image.svg", "archive.zip", ".pdf", ""])
def test_rejects_unsupported_or_empty_names(tmp_path, name):
	with pytest.raises(ValueError, match="Unsupported file type"):
		storage.save_file(_upload(name), str(tmp_path))
	assert not any(tmp_path.iterdir()), "nothing is written for rejected files"


def test_sanitises_the_original_name_before_checking_the_extension(tmp_path):
	saved = storage.save_file(_upload("../../etc/passwd.pdf"), str(tmp_path))
	assert (tmp_path / saved).exists() and "/" not in saved and ".." not in saved
