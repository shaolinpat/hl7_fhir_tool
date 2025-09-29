# tests/test_logging_utils.py
"""
tests for hls_fhir_tool.logging_utils
"""

import io
import pytest

from hl7_fhir_tool.logging_utils import configure_logging


def test_configure_logging_rejects_non_int_verbosity():
    with pytest.raises(TypeError, match=r"^verbosity must be int"):
        configure_logging("load")


def test_configure_logging_rejects_negative_verbosity():
    with pytest.raises(ValueError, match=r"^verbosity must be non-negative"):
        configure_logging(-1)


def test_configure_logging_sets_info_level(capsys):
    logger = configure_logging(verbosity=0)
    logger.info("hello info")
    logger.debug("hidden debug")

    out, _ = capsys.readouterr()
    assert "hello info" in out
    assert "hidden debug not in out"


def test_configure_logging_sets_debug_level(capsys):
    logger = configure_logging(verbosity=1)
    logger.debug("visible debug")

    out, _ = capsys.readouterr()
    assert "visible debug" in out


def test_configure_logging_accepts_custom_stream():
    buf = io.StringIO()
    logger = configure_logging(verbosity=0, stream=buf)
    logger.info("routed message")

    contents = buf.getvalue()
    assert "routed message" in contents


def test_configure_logging_rejects_bad_stream():
    class NotAStream:
        pass

    with pytest.raises(
        TypeError, match=r"^stream must be file-like \(support .write\(...\)\)"
    ):
        configure_logging(0, stream=NotAStream())
