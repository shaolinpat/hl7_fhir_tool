# tests/test_cli.py
"""
Tests for hl7_fhir_tool/cli.
"""

import datetime as _dt
import io
import json as _json
import os
import pytest
import runpy
import sys
import types

from decimal import Decimal as _Decimal
from pathlib import Path
from uuid import UUID as _UUID

from hl7_fhir_tool import cli


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

HL7_TEXT = (
    "MSH|^~\\&|HIS|RIH|EKG|EKG|20250101123000||ADT^A01|MSG00001|P|2.5.1\n"
    "EVN|A01|20250101123000\n"
    "PID|1||12345^^^MRN||Doe^John||19700101|M\n"
    "PV1|1|I|2000^2012^01||||1234^Physician^Primary\n"
)


def write_hl7(tmp_path: Path, name: str = "msg.hl7", text: str = HL7_TEXT) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------------------
# Happy paths
# ------------------------------------------------------------------------------


def test_parse_hl7_ok(tmp_path, capsys):
    p = write_hl7(tmp_path)
    code = cli.main(["parse-hl7", str(p)])
    out, _ = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert "MSH|" in out and "PID|" in out


def test_parse_fhir_json_ok(tmp_path, capsys):
    j = tmp_path / "patient.json"
    j.write_text(_json.dumps({"resourceType": "Patient", "id": "p1"}), encoding="utf-8")
    code = cli.main(["parse-fhir", str(j)])
    out, _ = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert out.strip().startswith("{") and out.strip().endswith("}")


def test_parse_fhir_xml_ok(tmp_path, capsys):
    x = tmp_path / "patient.xml"
    x.write_text(
        '<Patient xmlns="http://hl7.org/fhir"><id value="p1"/></Patient>',
        encoding="utf-8",
    )
    code = cli.main(["parse-fhir", str(x)])
    out, _ = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert '"resourceType"' in out and '"Patient"' in out


def test_transform_stdout_pretty_ok(tmp_path, capsys):
    p = write_hl7(tmp_path)
    code = cli.main(["transform", str(p), "--stdout", "--pretty"])
    out, _ = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert out.strip().startswith("{") and out.strip().endswith("}")
    assert '"resourceType"' in out


# ------------------------------------------------------------------------------
# _validate_existing_file
# ------------------------------------------------------------------------------


def test_parse_hl7_file_not_found(tmp_path):
    missing = tmp_path / "nope.hl7"
    code = cli.main(["parse-hl7", str(missing)])
    assert code == cli.EXIT_ERR


def test_parse_hl7_path_is_directory(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    code = cli.main(["parse-hl7", str(d)])
    assert code == cli.EXIT_ERR


def test_parse_hl7_not_readable(tmp_path, monkeypatch):
    p = write_hl7(tmp_path)
    real_access = os.access
    # force unreadable
    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: (
            False if Path(path) == p and (mode & os.R_OK) else real_access(path, mode)
        ),
    )
    code = cli.main(["parse-hl7", str(p)])
    assert code == cli.EXIT_ERR


# ------------------------------------------------------------------------------
# _validate_fhir_suffix
# ------------------------------------------------------------------------------


def test_parse_fhir_unsupported_suffix(tmp_path):
    bad = tmp_path / "z.txt"
    bad.write_text("{}", encoding="utf-8")
    code = cli.main(["parse-fhir", str(bad)])
    assert code == cli.EXIT_ERR


# ------------------------------------------------------------------------------
# _validate_output_mode
# ------------------------------------------------------------------------------


def test_validate_output_mode_none_is_ok(tmp_path, capsys):
    # return when output_dir is None
    p = write_hl7(tmp_path)
    code = cli.main(["transform", str(p), "--stdout"])
    out, _ = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert out.strip()  # some JSON printed


def test_validate_output_mode_mkdir_raises_oserror(tmp_path, monkeypatch):
    p = write_hl7(tmp_path)
    bad = tmp_path / "nope"

    # mkdir raising OSError
    orig_mkdir = Path.mkdir

    def boom_mkdir(self, parents=False, exist_ok=False):
        raise OSError("mkdir-fail")

    monkeypatch.setattr(Path, "mkdir", boom_mkdir)
    try:
        code = cli.main(["transform", str(p), "-o", str(bad)])
        assert code == cli.EXIT_ERR
    finally:
        monkeypatch.setattr(Path, "mkdir", orig_mkdir, raising=False)


def test_validate_output_mode_dir_not_writable(tmp_path, monkeypatch):
    p = write_hl7(tmp_path)
    outdir = tmp_path / "outdir"
    outdir.mkdir(parents=True, exist_ok=True)
    real_access = os.access
    # deny W_OK for this directory
    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: (
            False
            if Path(path) == outdir and (mode & os.W_OK)
            else real_access(path, mode)
        ),
    )
    code = cli.main(["transform", str(p), "-o", str(outdir)])
    assert code == cli.EXIT_ERR


# ------------------------------------------------------------------------------
# _read_text_input
# ------------------------------------------------------------------------------


def test_read_text_input_file_not_found(tmp_path, monkeypatch):
    p = tmp_path / "ghost.hl7"
    # Make _read_text_input raise FileNotFoundError
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, **k: (_ for _ in ()).throw(FileNotFoundError("nope")),
    )
    with pytest.raises(cli.HL7FHIRToolError, match=r"^File not found"):
        cli._read_text_input(p)


def test_read_text_input_permission_error(tmp_path, monkeypatch):
    p = tmp_path / "x.hl7"
    p.write_text("x", encoding="utf-8")

    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(cli.HL7FHIRToolError, match=r"^Permission denied"):
        cli._read_text_input(p)


def test_read_text_input_oserror(tmp_path, monkeypatch):
    p = tmp_path / "x2.hl7"
    p.write_text("x", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("weird-os")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(cli.HL7FHIRToolError, match=r"^Failed to read"):
        cli._read_text_input(p)


# ------------------------------------------------------------------------------
# _resource_to_json_str
# ------------------------------------------------------------------------------


def test_resource_to_json_str_pydantic_helpers_raise_to_generic():
    class R:
        def model_dump_json(self, **k):
            raise RuntimeError("mdj-fail")

        def model_dump(self, **k):
            raise RuntimeError("md-fail")

        def dict(self, **k):
            raise RuntimeError("dict-fail")

    s = cli._resource_to_json_str(R(), pretty=False)
    _json.loads(s)  # should parse


def test_resource_to_json_str_date_decimal_uuid_iterables_mappings_and_str(monkeypatch):
    # date -> isoformat
    date = _dt.date(2025, 1, 2)
    s = cli._resource_to_json_str(date, pretty=False)
    assert _json.loads(s) == "2025-01-02"

    # Decimal
    s = cli._resource_to_json_str(_Decimal("3.14"), pretty=False)
    assert _json.loads(s) == "3.14"

    # UUID
    u = _UUID("12345678-1234-5678-1234-567812345678")
    s = cli._resource_to_json_str(u, pretty=False)
    assert _json.loads(s) == str(u)

    # Iterable (tuple)
    s = cli._resource_to_json_str((1, 2, 3), pretty=False)
    assert _json.loads(s) == [1, 2, 3]
    s = cli._resource_to_json_str({"k": 1}, pretty=False)
    assert _json.loads(s) == {"k": 1}

    # last resort str()
    class X:
        __slots__ = ()

        def __str__(self):
            return "ZZZ"

    s = cli._resource_to_json_str(X(), pretty=False)
    assert _json.loads(s) == "ZZZ"

    def b64_boom(b):
        raise RuntimeError("nope")

    monkeypatch.setattr("base64.b64encode", b64_boom)
    s = cli._resource_to_json_str(b"hi", pretty=False)
    assert _json.loads(s) == "hi"  # decoded utf-8 fallback


def test_resource_to_json_str_json_dumps_failure_raises(monkeypatch):
    # Force final json.dumps to fail
    orig_dumps = cli.json.dumps
    try:
        monkeypatch.setattr(
            cli.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("nope"))
        )
        with pytest.raises(
            cli.HL7FHIRToolError, match=r"^Resource is not JSON serializable"
        ):
            cli._resource_to_json_str(object(), pretty=False)
    finally:
        monkeypatch.setattr(cli.json, "dumps", orig_dumps)


# ------------------------------------------------------------------------------
# _write_resources_to_dir
# ------------------------------------------------------------------------------


def test_write_resources_to_dir_success_and_oserror(tmp_path, monkeypatch):
    class R1:
        resource_type = "Patient"

    class R2:
        resourceType = "Encounter"

    outdir = tmp_path / "outA"
    cli._write_resources_to_dir([R1(), R2()], outdir, pretty=False)
    assert (outdir / "01_Patient.json").exists()
    assert (outdir / "02_Encounter.json").exists()

    # Now simulate an OSError only for the 3rd file write, using the ORIGINAL write_text
    orig_write_text = Path.write_text

    call_count = {"n": 0}

    def guarded_write_text(self, txt, *, encoding="utf-8"):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise OSError("disk-full")
        return orig_write_text(self, txt, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    with pytest.raises(cli.HL7FHIRToolError, match=r"^Failed to write"):
        cli._write_resources_to_dir([R1(), R2(), R1()], tmp_path / "outB", pretty=False)

    # clean up with monkeypatch
    monkeypatch.setattr(Path, "write_text", orig_write_text, raising=False)


# ------------------------------------------------------------------------------
# _write_resources_to_stdout
# ------------------------------------------------------------------------------


def test_write_resources_to_stdout_ndjson_and_except(capsys):
    class ResGoodJson:
        def model_dump_json(self, **k):
            return _json.dumps({"id": "good"})

    class ResBadJson:
        def model_dump_json(self, **k):
            return "{not-json}"  # json.loads will fail

    cli._write_resources_to_stdout([ResGoodJson(), ResBadJson()], pretty=False)
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == '{"id":"good"}'
    assert out[1] == "{not-json}"


# ------------------------------------------------------------------------------
# _cmd_transform
# ------------------------------------------------------------------------------


def test_cmd_transform_no_transformer_registered(tmp_path, monkeypatch):
    p = write_hl7(tmp_path)
    monkeypatch.setattr("hl7_fhir_tool.cli.get_transformer", lambda _msg: None)
    code = cli.main(["transform", str(p)])
    assert code == cli.EXIT_ERR


def test_cmd_transform_default_output_dir_validated_and_writes(tmp_path, monkeypatch):
    p = write_hl7(tmp_path)

    class Cfg:
        def __init__(self, d):
            self.default_output_dir = d

    default_dir = tmp_path / "default_out"
    monkeypatch.setattr("hl7_fhir_tool.cli.load_config", lambda _cfg: Cfg(default_dir))

    class Xformer:
        def transform(self, _msg):
            class R:
                resource_type = "Patient"

                def model_dump_json(self, **k):
                    return _json.dumps({"resourceType": "Patient"})

            return [R()]

    monkeypatch.setattr("hl7_fhir_tool.cli.get_transformer", lambda _msg: Xformer())
    code = cli.main(["transform", str(p)])  # not --stdout -> write path
    assert code == cli.EXIT_OK
    assert (default_dir / "01_Patient.json").exists()


def test_cmd_transform_list_prints_and_exits_ok(tmp_path, capsys):
    p = write_hl7(tmp_path)
    code = cli.main(["transform", str(p), "--list"])
    out, _ = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert "ADT^A01" in out


# ------------------------------------------------------------------------------
# main()
# ------------------------------------------------------------------------------


def test_main_keyboardinterrupt(tmp_path, monkeypatch):
    p = write_hl7(tmp_path)
    monkeypatch.setattr(
        "hl7_fhir_tool.cli._cmd_parse_hl7",
        lambda _: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    code = cli.main(["parse-hl7", str(p)])
    assert code == cli.EXIT_ERR


def test_main_unknown_command_path(monkeypatch):
    # Build a dummy parser
    class DummyParser:
        def parse_args(self, argv=None):
            # must include verbose because main() calls configure_logging(args.verbose)
            return types.SimpleNamespace(cmd="weird", verbose=0)

        def error(self, msg):
            # override to NOT raise SystemExit so main() reaches return EXIT_CLI
            return None

    monkeypatch.setattr("hl7_fhir_tool.cli._build_parser", lambda: DummyParser())
    code = cli.main([])
    assert code == cli.EXIT_CLI


# ------------------------------------------------------------------------------
# __main__
# ------------------------------------------------------------------------------


def test_main_dunder_name_runs_ok(monkeypatch):
    # Execute module as __main__ cleanly
    for k in list(sys.modules.keys()):
        if k.startswith("hl7_fhir_tool"):
            sys.modules.pop(k, None)

    old_argv, old_stdin = sys.argv, sys.stdin
    try:
        sys.argv = ["hl7-fhir", "parse-hl7", "-"]
        sys.stdin = io.StringIO(HL7_TEXT)
        with pytest.raises(SystemExit) as e:
            runpy.run_module("hl7_fhir_tool.cli", run_name="__main__")
        assert e.value.code == 0
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
