"""Small regression tests for upload filename helpers."""

import os

# Windows sandbox tests cannot create Loguru's multiprocessing queue. Production
# keeps asynchronous logging enabled; this only affects this Python process.
os.environ["LOG_ENQUEUE"] = "false"

from app.utils.file_utils import get_file_extension, sanitize_filename


def test_get_file_extension_is_lowercase() -> None:
    assert get_file_extension("Runbook.PDF") == "pdf"
    assert get_file_extension("no-extension") == ""


def test_sanitize_filename_removes_path_characters() -> None:
    filename = sanitize_filename("../CPU report?.md")

    assert "/" not in filename
    assert "\\" not in filename
    assert " " not in filename
    assert filename.endswith(".md")
