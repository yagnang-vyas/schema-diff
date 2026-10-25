"""CLI end to end against real databases: output formats, exit codes, masking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemadiff.cli import main
from tests.integration.conftest import Db


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def urls(drift: Db, monkeypatch: pytest.MonkeyPatch) -> Db:
    monkeypatch.setenv("SD_SRC", drift.url)
    monkeypatch.setenv("SD_TGT", drift.url)
    return drift


def compare_args(*extra: str) -> list[str]:
    return [
        "compare",
        "--source-env",
        "SD_SRC",
        "--target-env",
        "SD_TGT",
        "--source-schema",
        "drift_source",
        "--target-schema",
        "drift_target",
        *extra,
    ]


def test_live_compare_text_reports_drift(urls: Db, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, *compare_args())
    assert code == 1
    assert "~ error   column orders.note" in out
    assert "- error   table audit_log" in out
    assert "+ error   table extra_table" in out
    assert "Summary:" in out
    assert "SD_SRC" in out
    assert err == ""


def test_live_compare_of_identical_schemas_exits_zero(
    urls: Db, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(
        capsys,
        "compare",
        "--source-env",
        "SD_SRC",
        "--target-env",
        "SD_TGT",
        "--source-schema",
        "drift_source",
        "--target-schema",
        "drift_copy",
        "--strict-column-order",
    )
    assert code == 0
    assert "No differences found." in out


def test_json_format_is_stable(urls: Db, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, *compare_args("--format", "json"))
    assert code == 1
    report = json.loads(out)
    assert report["format_version"] == 1
    assert report["source"]["schema"] == "drift_source"
    assert report["target"]["dialect"] == urls.dialect
    assert report["summary"]["total"] == len(report["changes"])
    assert set(report["summary"]) == {"error", "warning", "note", "total"}
    first = report["changes"][0]
    assert set(first) == {
        "kind",
        "object",
        "path",
        "table",
        "severity",
        "attribute",
        "source",
        "target",
        "note",
    }
    assert out == json.dumps(report, indent=2, sort_keys=True) + "\n"


def test_markdown_format(urls: Db, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, *compare_args("--format", "markdown"))
    assert code == 1
    assert out.startswith("# SchemaDiff report")
    assert "## `orders`" in out
    assert "| --- | --- | --- | --- | --- |" in out
    assert "`orders.note`" in out


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (["--fail-on", "never"], 0),
        (["--fail-on", "error"], 1),
        (["--include-tables", "tags", "--fail-on", "error", "--exclude-tables", ""], 1),
        (["--include-tables", "equivalent_forms", "--fail-on", "note"], 1),  # views / enums
    ],
)
def test_exit_codes(
    urls: Db, capsys: pytest.CaptureFixture[str], extra: list[str], expected: int
) -> None:
    code, _, _ = run(capsys, *compare_args(*extra))
    assert code == expected


def test_fail_on_threshold_with_only_notes(urls: Db, capsys: pytest.CaptureFixture[str]) -> None:
    """With only note-level drift left, --fail-on warning passes and --fail-on note fails."""
    base = [
        "compare",
        "--source-env",
        "SD_SRC",
        "--target-env",
        "SD_TGT",
        "--source-schema",
        "drift_source",
        "--target-schema",
        "drift_copy",
    ]
    assert run(capsys, *base, "--fail-on", "note")[0] == 0
    urls.run_script(
        "COMMENT ON TABLE drift_copy.tags IS 'tags';\n"
        if urls.dialect == "postgresql"
        else "ALTER TABLE drift_copy.tags COMMENT = 'tags';\n"
    )
    assert run(capsys, *base, "--fail-on", "warning")[0] == 0
    assert run(capsys, *base, "--fail-on", "note")[0] == 1
    urls.load("drift_source.sql", rename=("drift_source", "drift_copy"))


def test_snapshot_workflow(urls: Db, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    code, out, _ = run(
        capsys, "snapshot", "--env", "SD_SRC", "--schema", "drift_source", "-o", str(a)
    )
    assert code == 0
    assert "wrote snapshot" in out
    assert (
        run(capsys, "snapshot", "--env", "SD_SRC", "--schema", "drift_target", "-o", str(b))[0] == 0
    )
    live = run(capsys, *compare_args("--format", "json"))[1]
    from_files = run(
        capsys,
        "compare",
        "--source-snapshot",
        str(a),
        "--target-snapshot",
        str(b),
        "--format",
        "json",
    )
    assert from_files[0] == 1
    live_changes = json.loads(live)["changes"]
    snap_changes = json.loads(from_files[1])["changes"]
    assert snap_changes == live_changes
    mixed = run(
        capsys,
        "compare",
        "--source-snapshot",
        str(a),
        "--target-env",
        "SD_TGT",
        "--target-schema",
        "drift_target",
        "--format",
        "json",
    )
    assert json.loads(mixed[1])["changes"] == live_changes


def test_command_line_url_warns_and_works(urls: Db, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(
        capsys,
        "compare",
        "--source",
        urls.url,
        "--target-env",
        "SD_TGT",
        "--source-schema",
        "drift_source",
        "--target-schema",
        "drift_copy",
    )
    assert code == 0
    assert "No differences found." in out
    assert "warning:" in err
    assert "shell history" in err
    assert "command-line URL" in out
