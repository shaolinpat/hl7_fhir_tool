# tests/test_config.py
"""
Tests for hl7_fhir_tool.config
"""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from hl7_fhir_tool.config import AppConfig, load_config


def test_load_config_defaults_when_path_is_none():
    cfg = load_config(None)
    assert isinstance(cfg, AppConfig)
    assert cfg.default_output_dir == Path("outputs")


def test_load_config_reads_default_output_dir(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("default_output_dir: custom_out\n")
    cfg = load_config(p)
    assert cfg.default_output_dir == Path("custom_out")


def test_load_config_empty_file_uses_defaults(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg.default_output_dir == Path("outputs")


def test_load_config_non_mapping_raises_type_error(tmp_path):
    p = tmp_path / "bad.yaml"
    # YAML list at top level, not a mapping/dict
    p.write_text("- item1\n- item2\n")
    with pytest.raises(
        TypeError, match=r"^Config file must contain a mapping at top level"
    ):
        load_config(p)


def test_load_config_invalid_yaml_raises_yaml_error(tmp_path):
    p = tmp_path / "invalid.yaml"
    p.write_text("default_output_dir: [unclosed_list\n")
    with pytest.raises(yaml.YAMLError, match=r"^while parsing a flow sequence"):
        load_config(p)


def test_appconfig_is_immutable():
    cfg = AppConfig()
    with pytest.raises(FrozenInstanceError, match=r"^cannot assign to field"):
        cfg.default_output_dir = Path("cannot_assign")
