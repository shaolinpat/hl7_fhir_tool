# src/hl7_fhir_tool/logging_utils.py
"""
Logging utilities for hl7_fhir_tool.

Provides a single entry point to configure root logging for CLI and library use.
"""

import logging
import sys
from typing import IO, Optional


_VERBOSITY_LEVELS = {
    0: logging.INFO,
    1: logging.DEBUG,  # any value >= 1 maps to DEBUG
}


def configure_logging(
    verbosity: int = 0, stream: Optional[IO[str]] = None
) -> logging.Logger:
    """
    Configure application-wide logging.

    Parameters
    ----------
    verbosity : int, default=0
        Verbosity level:
        - 0 -> INFO
        - 1 or higher -> DEBUG
        Must be a non-negative integer.
    stream : IO[str] or None, default=None
        Target stream for the StreamHandler. Defaults to sys.stdout if None.

    Returns
    -------
    logging.Logger
        The configured root logger.

    Raises
    ------
    TypeError
        If verbosity is not an int, or if a stream is provided that does not
        have a write method.
    ValueError
        If verbosity is negative.
    """
    # Validate verbosity
    if not isinstance(verbosity, int):
        raise TypeError(f"verbosity must be int, got {type(verbosity).__name__}")
    if verbosity < 0:
        raise ValueError(f"verbosity must be non-negative, got {verbosity}")

    # Determine level
    level = _VERBOSITY_LEVELS.get(verbosity, logging.DEBUG)

    # Validate/resolve stream
    if stream is None:
        stream = sys.stdout
    else:
        # minimal file-like validation
        if not hasattr(stream, "write"):
            raise TypeError("stream must be file-like (support .write(...))")

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    # Replace only existing StreamHandlers; leave other handlers intact (e.g.,
    #   FileHandler)
    root.handlers = [
        h for h in root.handlers if not isinstance(h, logging.StreamHandler)
    ]
    root.addHandler(handler)
    root.setLevel(level)

    return root
