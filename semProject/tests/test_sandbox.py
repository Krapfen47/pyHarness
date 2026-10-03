"""The Docker sandbox, tested WITHOUT Docker: we check the command line it
would run (the security flags) and how it behaves when Docker is missing.
The real container runs are in test_docker_integration.py."""

import pytest

from harness.execution import UNAVAILABLE, DockerSandbox, SandboxError
from harness.limits import Limits


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "acceptance").mkdir()
    return DockerSandbox(tmp_path / "work", {"tests": "python -m pytest -q 'tests/unit'"},
                         "harness-demo:1", Limits(), env={"PYTHONPATH": "/work/src"},
                         acceptance_dir=tmp_path / "acceptance", docker="docker")


def test_container_is_locked_down(sandbox):
    argv = sandbox.docker_command("box-1", "python -m pytest")
    line = " ".join(argv)
    for flag in ["--network none", "--read-only", "--cap-drop ALL",
                 "--security-opt no-new-privileges", "--user 1000:1000", "--rm",
                 "--memory", "--pids-limit"]:
        assert flag in line, flag
    mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount"]
    assert len(mounts) == 2
    assert all(m.endswith(",readonly") for m in mounts)
    assert any("target=/work," in m for m in mounts)
    assert any("target=/acceptance," in m for m in mounts)


def test_command_is_split_without_a_shell(sandbox):
    argv = sandbox.docker_command("box-1", "python -m pytest -q 'tests/unit'")
    assert argv[-5:] == ["python", "-m", "pytest", "-q", "tests/unit"]
    assert argv[-6] == "harness-demo:1"  # the image comes right before the command


def test_host_secrets_are_not_passed_into_the_container(sandbox, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-very-secret")
    line = " ".join(sandbox.docker_command("box-1", "env"))
    assert "sk-very-secret" not in line
    assert "PYTHONPATH=/work/src" in line  # only what the task file asked for


def test_missing_docker_makes_checks_unavailable(tmp_path):
    sandbox = DockerSandbox(tmp_path, {"tests": "pytest"}, "img", Limits(),
                            docker=str(tmp_path / "no-such-docker.exe"))
    result = sandbox.run_check("tests")
    assert result.status == UNAVAILABLE
    assert result.passed is False
    sandbox.stop_processes()  # must not crash either


def test_unknown_check_is_unavailable(sandbox):
    assert sandbox.run_check("deploy").status == UNAVAILABLE


def test_path_with_comma_is_refused(tmp_path):
    folder = tmp_path / "a,b"
    folder.mkdir()
    sandbox = DockerSandbox(folder, {}, "img", Limits(), docker="docker")
    with pytest.raises(SandboxError):
        sandbox.docker_command("box", "true")
