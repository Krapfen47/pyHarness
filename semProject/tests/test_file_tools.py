"""Handout test "File tools": read, search and edit the intended files;
reject a path outside the allowed area."""

import os

import pytest
from conftest import PRICING, snapshot

from harness.tools import Denied, PathGuard


def run(toolbox, tool, **args):
    return toolbox.run({"tool": tool, "args": args})


def test_list_files_hides_hidden_files(toolbox):
    files = run(toolbox, "list_files")["output"]["files"]
    assert "src/shop/pricing.py" in files
    assert not any(f.startswith(".") for f in files)  # no .env, no .git


def test_read_file(toolbox):
    result = run(toolbox, "read_file", path="src/shop/pricing.py")
    assert result["status"] == "ok"
    assert result["output"]["content"] == PRICING
    assert result["output"]["truncated"] is False


def test_search_finds_line_numbers(toolbox):
    matches = run(toolbox, "search_files", query="return sum")["output"]["matches"]
    assert matches == [{"path": "src/shop/pricing.py", "line": 2, "text": "return sum(prices)"}]


def test_edit_changes_only_the_intended_file(toolbox, repo):
    before = snapshot(repo)
    result = run(toolbox, "edit_file", path="src/shop/pricing.py",
                 old="return sum(prices)", new="return round(sum(prices), 2)")
    assert result["status"] == "ok"

    after = snapshot(repo)
    changed = [path for path in before if before[path] != after[path]]
    assert changed == ["src/shop/pricing.py"]
    assert b"round(sum(prices), 2)" in after["src/shop/pricing.py"]


def test_edit_needs_a_unique_match(toolbox, repo):
    (repo / "src/shop/twice.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = run(toolbox, "edit_file", path="src/shop/twice.py", old="x = 1", new="x = 2")
    assert result["status"] == "error"
    assert "occurs 2 times" in result["output"]


def test_empty_file_can_be_filled_with_an_empty_old(toolbox, repo):
    result = run(toolbox, "edit_file", path="src/shop/__init__.py", old="", new="X = 1\n")
    assert result["status"] == "ok"
    assert (repo / "src/shop/__init__.py").read_text() == "X = 1\n"
    # ...but on a file with content, an empty `old` is still an error.
    again = run(toolbox, "edit_file", path="src/shop/__init__.py", old="", new="Y = 2\n")
    assert again["status"] == "error"


def test_edit_keeps_windows_line_endings(toolbox, repo):
    (repo / "src/shop/crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    run(toolbox, "edit_file", path="src/shop/crlf.py", old="b = 2", new="b = 3")
    assert (repo / "src/shop/crlf.py").read_bytes() == b"a = 1\r\nb = 3\r\n"


def test_edit_that_uses_an_undefined_name_gets_a_warning(toolbox, repo):
    result = run(toolbox, "edit_file", path="src/shop/pricing.py",
                 old="return sum(prices)", new="return apply_discount(sum(prices))")
    assert result["status"] == "ok"  # saved anyway: a second edit may define it
    assert "WARNING" in result["output"]
    assert "line 2: undefined name 'apply_discount'" in result["output"]


def test_lint_only_reports_problems_the_edit_introduced(toolbox, repo):
    # This file already has an undefined name. That's not the model's fault,
    # so an unrelated edit must not be blamed for it.
    (repo / "src/shop/old.py").write_text("x = missing\ny = 1\n", encoding="utf-8")
    result = run(toolbox, "edit_file", path="src/shop/old.py", old="y = 1", new="y = 2")
    assert result["output"] == "edited src/shop/old.py"


def test_new_file_with_a_syntax_error_gets_a_warning(toolbox):
    result = run(toolbox, "write_file", path="src/shop/broken.py", content="def f(:\n")
    assert "syntax error" in result["output"]


def test_write_file_creates_but_never_overwrites(toolbox, repo):
    assert run(toolbox, "write_file", path="src/shop/tax.py", content="RATE = 0.2\n")[
        "status"] == "ok"
    assert (repo / "src/shop/tax.py").read_text() == "RATE = 0.2\n"
    again = run(toolbox, "write_file", path="src/shop/tax.py", content="RATE = 0\n")
    assert again["status"] == "error"
    assert (repo / "src/shop/tax.py").read_text() == "RATE = 0.2\n"


@pytest.mark.parametrize("path", [
    "../outside.txt",  # climbing out with ..
    "src/../../outside.txt",  # .. hidden in the middle
    "/etc/passwd",  # absolute (Unix style)
    "C:\\Windows\\win.ini",  # absolute (Windows style)
    ".env",  # hidden file with secrets
    ".git/config",  # git internals
    "",  # empty
])
def test_rejects_paths_outside_the_allowed_area(toolbox, path):
    result = run(toolbox, "read_file", path=path)
    assert result["status"] == "denied"


def test_absolute_path_into_the_repo_is_rejected_too(toolbox, repo):
    # Even a path that points INTO the repo must be relative: one simple rule
    # is easier to get right than "absolute is fine if it's inside".
    result = run(toolbox, "read_file", path=str(repo / "src/shop/pricing.py"))
    assert result["status"] == "denied"


def test_writing_outside_the_writable_area_is_denied(toolbox, repo):
    before = snapshot(repo)
    result = run(toolbox, "edit_file", path="README.md", old="# Shop", new="# Hacked")
    assert result["status"] == "denied"
    assert "outside the writable area" in result["output"]
    assert snapshot(repo) == before


def test_writable_area_is_a_folder_not_a_name_prefix(repo):
    guard = PathGuard(repo, ("src/shop",))
    assert guard.is_writable("src/shop/pricing.py")
    assert not guard.is_writable("src/shopping/cart.py")  # starts with "src/shop" too!


def test_symlink_leading_out_of_the_repo_is_rejected(repo, tmp_path):
    link = repo / "src" / "shop" / "escape.txt"
    try:
        os.symlink(tmp_path / "outside.txt", link)
    except OSError:
        pytest.skip("creating symlinks needs extra rights on this Windows machine")
    with pytest.raises(Denied):
        PathGuard(repo, ("src/shop",)).resolve("src/shop/escape.txt")
