"""CLI behaviour that needs no database: validation, exit codes, error masking."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from schemadiff import cli, snapshot
from schemadiff.model import Column, Index, Schema, Table

Snaps = dict[str, Path]


def make_schema(dialect: str = "postgresql", note_type: str = "integer") -> Schema:
    users = Table(
        name="users",
        columns={
            "id": Column("id", 1, "integer", False, identity=True),
            "note": Column("note", 2, note_type, True),
        },
        primary_key=("id",),
        indexes={"idx": Index("idx", ("note",), method="btree")},
    )
    return Schema(dialect=dialect, schema="public", server_version="16.0", tables={"users": users})


@pytest.fixture
def snaps(tmp_path: Path) -> Snaps:
    paths = {
        "a": tmp_path / "a.json",
        "same": tmp_path / "same.json",
        "b": tmp_path / "b.json",
        "mysql": tmp_path / "mysql.json",
    }
    snapshot.save(make_schema(), paths["a"], "2026-01-01T00:00:00Z")
    snapshot.save(make_schema(), paths["same"], "2026-02-02T00:00:00Z")
    snapshot.save(make_schema(note_type="text"), paths["b"], "2026-01-01T00:00:00Z")
    snapshot.save(make_schema("mysql"), paths["mysql"], "2026-01-01T00:00:00Z")
    return paths


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def compare(a: Path, b: Path, *extra: str) -> list[str]:
    return ["compare", "--source-snapshot", str(a), "--target-snapshot", str(b), *extra]


def test_identical_snapshots_exit_zero(capsys: pytest.CaptureFixture[str], snaps: Snaps) -> None:
    code, out, err = run(capsys, *compare(snaps["a"], snaps["same"]))
    assert (code, err) == (0, "")
    assert "No differences found." in out


def test_drift_exits_one_and_reports(capsys: pytest.CaptureFixture[str], snaps: Snaps) -> None:
    code, out, _ = run(capsys, *compare(snaps["a"], snaps["b"]))
    assert code == 1
    assert "~ error   column users.note  type: integer -> text" in out
    assert "snapshot a.json (PostgreSQL 16.0, schema public)" in out
    assert "Summary: 1 error, 0 warnings, 0 notes (1 changes)" in out


@pytest.mark.parametrize(
    ("fail_on", "expected"), [("error", 1), ("warning", 1), ("note", 1), ("never", 0)]
)
def test_fail_on(
    capsys: pytest.CaptureFixture[str],
    snaps: Snaps,
    fail_on: str,
    expected: int,
) -> None:
    assert run(capsys, *compare(snaps["a"], snaps["b"], "--fail-on", fail_on))[0] == expected


def test_formats(capsys: pytest.CaptureFixture[str], snaps: Snaps) -> None:
    _, js, _ = run(capsys, *compare(snaps["a"], snaps["b"], "--format", "json"))
    assert json.loads(js)["changes"][0]["attribute"] == "type"
    _, md, _ = run(capsys, *compare(snaps["a"], snaps["b"], "--format", "markdown"))
    assert "# SchemaDiff report" in md
    _, md_same, _ = run(capsys, *compare(snaps["a"], snaps["same"], "--format", "markdown"))
    assert "No differences found." in md_same
    _, js_same, _ = run(capsys, *compare(snaps["a"], snaps["same"], "--format", "json"))
    assert json.loads(js_same)["changes"] == []


def test_table_filter_flags(capsys: pytest.CaptureFixture[str], snaps: Snaps) -> None:
    code, _, _ = run(capsys, *compare(snaps["a"], snaps["b"], "--exclude-tables", "users"))
    assert code == 0
    code, _, _ = run(capsys, *compare(snaps["a"], snaps["b"], "--include-tables", "nothing,x*"))
    assert code == 0


def test_cross_dialect_is_a_usage_error(capsys: pytest.CaptureFixture[str], snaps: Snaps) -> None:
    code, out, err = run(capsys, *compare(snaps["a"], snaps["mysql"]))
    assert code == 2
    assert out == ""
    assert "cannot compare a postgresql schema with a mysql schema" in err


def test_missing_and_corrupt_snapshots(
    capsys: pytest.CaptureFixture[str],
    snaps: Snaps,
    tmp_path: Path,
) -> None:
    code, _, err = run(capsys, *compare(snaps["a"], tmp_path / "nope.json"))
    assert (code, "cannot read snapshot" in err) == (2, True)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    code, _, err = run(capsys, *compare(snaps["a"], bad))
    assert (code, "not valid JSON" in err) == (2, True)


def test_usage_errors_exit_two(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (
        [],
        ["compare"],
        ["compare", "--source-env", "A"],
        ["compare", "--source-env", "A", "--source", "x", "--target-env", "B"],
        ["snapshot", "--env", "A"],
        ["compare", "--fail-on", "bogus"],
    ):
        with pytest.raises(SystemExit) as info:
            cli.main(argv)
        assert info.value.code == 2
        capsys.readouterr()


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.startswith("schemadiff ")


def test_missing_environment_variable(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    snaps: Snaps,
) -> None:
    monkeypatch.delenv("SD_NOPE", raising=False)
    code, _, err = run(
        capsys, "compare", "--source-env", "SD_NOPE", "--target-snapshot", str(snaps["a"])
    )
    assert code == 2
    assert "SD_NOPE" in err


def test_bad_url_is_reported_without_echoing_it(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    snaps: Snaps,
) -> None:
    monkeypatch.setenv("SD_BAD", "oracle://user:hunter2@host/db")
    code, _, err = run(
        capsys, "compare", "--source-env", "SD_BAD", "--target-snapshot", str(snaps["a"])
    )
    assert code == 2
    assert "hunter2" not in err
    assert "unsupported database dialect" in err


def test_connection_refused_is_masked(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    snaps: Snaps,
) -> None:
    for scheme in ("postgresql", "mysql"):
        monkeypatch.setenv("SD_DEAD", f"{scheme}://user:Pw-s3cret!@127.0.0.1:1/db")
        code, out, err = run(
            capsys, "compare", "--source-env", "SD_DEAD", "--target-snapshot", str(snaps["a"])
        )
        assert code == 2
        assert out == ""
        assert "Pw-s3cret" not in err
        assert "Pw-s3cret" not in out
        assert "127.0.0.1" in err


def test_command_line_url_masked_on_failure(
    capsys: pytest.CaptureFixture[str],
    snaps: Snaps,
) -> None:
    code, _, err = run(
        capsys,
        "compare",
        "--source",
        "postgresql://user:Pw-s3cret!@127.0.0.1:1/db",
        "--target-snapshot",
        str(snaps["a"]),
    )
    assert code == 2
    assert "Pw-s3cret" not in err
    assert "shell history" in err


def test_snapshot_command_url_warning_and_failure(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, _, err = run(
        capsys,
        "snapshot",
        "--url",
        "mysql://user:Pw-s3cret!@127.0.0.1:1/db",
        "-o",
        str(tmp_path / "x.json"),
    )
    assert code == 2
    assert "Pw-s3cret" not in err
    assert "--env" in err
    assert not (tmp_path / "x.json").exists()


def test_interrupt_and_broken_pipe_and_unexpected_errors(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    snaps: Snaps,
) -> None:
    argv = compare(snaps["a"], snaps["b"])

    def interrupted(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "diff_schemas", interrupted)
    assert run(capsys, *argv)[0] == 130

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("kaput s3cr3t-token")

    from schemadiff.urls import register_secret

    register_secret("s3cr3t-token")
    monkeypatch.setattr(cli, "diff_schemas", boom)
    code, _, err = run(capsys, *argv)
    assert code == 2
    assert "RuntimeError" in err
    assert "s3cr3t-token" not in err


def test_broken_pipe_returns_141(
    monkeypatch: pytest.MonkeyPatch,
    snaps: Snaps,
    tmp_path: Path,
) -> None:
    sink = open(tmp_path / "out.txt", "w")  # noqa: SIM115 - needs a real file descriptor
    saved_fd = None

    class ClosedPipe(io.TextIOBase):
        def fileno(self) -> int:
            return sink.fileno()

        def write(self, _s: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            return None

    import os

    saved_fd = os.dup(sink.fileno())
    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    try:
        assert cli.main(compare(snaps["a"], snaps["b"])) == 141
    finally:
        os.dup2(saved_fd, sink.fileno())
        os.close(saved_fd)
        sink.close()


def test_module_entry_point() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "schemadiff", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("schemadiff ")
