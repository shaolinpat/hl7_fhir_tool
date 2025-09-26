# src/hl7_fhir_tool/config.py
"""
Configuration utilities for hl7_fhir_tool.

Provides a simple dataclass-based configuration object and a loader that reads
YAML configuration files when present.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml


@dataclass(frozen=True)
class AppConfig:
    """
    Immutable application configuration.

    Attributes
    ----------
    default_output_dir : Path
        Directory where output files (e.g., transformed FHIR JSON) will be
            written.
    """

    default_output_dir: Path = Path("outputs")


def load_config(path: Optional[Path]) -> AppConfig:
    """
    Load application configuration from a YAML file.

    Parameters
    ----------
    path : Path or None
        Path to a YAML config file. If None, defaults are used.

    Returns
    -------
    AppConfig
        The loaded configuration.

    Raises
    ------
    TypeError
        If the YAML file does not parse to a mapping at the top level.
    yaml.YAMLError
        If the file is not valid YAML.
    """
    if path is None:
        return AppConfig()

    data: Any = yaml.safe_load(path.read_text())

    if data is None:
        return AppConfig()

    if not isinstance(data, Mapping):
        raise TypeError(
            f"Config file must contain a mapping at top level, "
            f"got {type(data).__name__}. "
            f"Config file: {path}"
        )

    out = data.get("default_output_dir", "outputs")
    return AppConfig(default_output_dir=Path(out))
