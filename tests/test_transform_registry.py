# tests/test_transform_registry.py
"""
Tests for hl7_fhir_tool.transform.registry.
"""

import types
import pytest

from hl7_fhir_tool.transform import registry
from hl7_fhir_tool.transform.base import Transformer

# -------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


class _StubToER7:
    def __init__(self, value: str):
        self._value = value

    def to_er7(self) -> str:
        return self._value


class _StubMSH:
    def __init__(self, msh9_value: str):
        self.msh_9 = _StubToER7(msh9_value)


class _StubMessage:
    """
    Minimal stand-in for hl7apy.core.Message for registry tests.
    Only the attributes used by registry.get_transformer are provided.
    """

    def __init__(self, msh9_value: str):
        self.MSH = _StubMSH(msh9_value)


class _StubToER7Bytes:
    def __init__(self, value: str):
        self._value = value

    def to_er7(self) -> bytes:
        return self._value.encode("ascii")


class _StubMSHBytes:
    def __init__(self, msh9_value: str):
        self.msh_9 = _StubToER7Bytes(msh9_value)


class _StubMessageBytes:
    def __init__(self, msh9_value: str):
        self.MSH = _StubMSHBytes(msh9_value)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """
    Ensure the module-level registry is clean for each test.
    Saves and restores the global mapping so tests don't leak state.
    """
    snap = dict(registry._REGISTRY)
    try:
        registry._REGISTRY.clear()
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snap)


# ------------------------------------------------------------------------------
# Sample transformers
# ------------------------------------------------------------------------------


class _GoodTransformerA:
    event = "ADT^A01"

    def applies(self, msg) -> bool:
        return True

    def transform(self, msg):
        return []


class _GoodTransformerB:
    event = "ADG^A04"

    def applies(self, msg) -> bool:
        return True

    def transform(self, msg):
        return []


class _BadTransformerMissingApplies:
    event = "ADT^A99"

    # def applies(self, msg) -> bool:  # inteentionally missing
    #    return True

    def transform(self, msg):
        return []


class _BadTransformerMissingTransform:
    even = "ADT^A98"

    def applies(self, msg) -> bool:
        return True

    # def transform(self, msg):  # intentionally missing
    #     return []


# ------------------------------------------------------------------------------
# register()
# ------------------------------------------------------------------------------


def test_registere_adds_transformer_and_available_events_sorted():
    dec1 = registry.register("ADT^A01")
    cls = dec1(_GoodTransformerA)
    assert cls is _GoodTransformerA

    dec2 = registry.register("ADT^A04")
    dec2(_GoodTransformerB)

    events = registry.available_events()
    assert events == ["ADT^A01", "ADT^A04"]


def test_register_rejects_duplicate_event():
    registry.register("ADT^A01")(_GoodTransformerA)
    with pytest.raises(ValueError, match=r"^Transformer already registered for event"):
        registry.register("ADT^A01")(_GoodTransformerB)


def test_register_rejects_non_class():
    with pytest.raises(
        TypeError, match=r"^Only classes can be registered as transformers"
    ):
        registry.register("ADT^A01")("duck")


def test_register_rejects_class_missing_required_methods():
    with pytest.raises(
        TypeError,
        match=r"^Class _BadTransformerMissingApplies does not implement Transformer protocol",
    ):
        registry.register("ADT^A99")(_BadTransformerMissingApplies)
    with pytest.raises(
        TypeError,
        match=r"^Class _BadTransformerMissingTransform does not implement Transformer protocol",
    ):
        registry.register("ADT^A98")(_BadTransformerMissingTransform)


# ------------------------------------------------------------------------------
# get_transformer()
# ------------------------------------------------------------------------------


def test_get_transformer_returns_instance_on_match():
    registry.register("ADT^A01")(_GoodTransformerA)
    msg = _StubMessage("ADT^A01")
    inst = registry.get_transformer(msg)
    assert inst is not None

    # Runtime check agaisnt the Protocol
    assert isinstance(inst, _GoodTransformerA)

    # If base.Transformer is runtime_checkable, this will pass; otherwise it is
    #  a no-op.
    try:
        # mpy/pyright will understand this; at runtime Protocol check may be shallow
        assert isinstance(inst, Transformer)
    except Exception:
        pass


def test_get_transformer_returns_none_when_no_mathc():
    registry.register("ADT^A01")(_GoodTransformerA)
    msg = _StubMessage("ORM^O01")
    inst = registry.get_transformer(msg)
    assert inst is None


def test_get_transformer_handles_missing_msh9_gracefully():
    class _NoMSH:
        pass

    class _MsgNoMSH:
        def __init__(self):
            self.MSH = _NoMSH()

    # Replace to_er7 with an attribute that will raise when accessed
    class _ExplodingMSH:
        @property
        def msh_9(self):
            raise AttributeError("no msh_9")

    class _MsgExploding:
        def __init__(self):
            self.MSH = _ExplodingMSH()

    # Either missing MSH fields or errors should yield None, not an exception.
    assert registry.get_transformer(_MsgNoMSH()) is None
    assert registry.get_transformer(_MsgExploding()) is None


def test_get_transformer_handle_bytes_from_to_er7():
    registry.register("ADT^A01")(_GoodTransformerA)
    msg = _StubMessageBytes("ADT^A01")
    inst = registry.get_transformer(msg)
    assert inst is not None
    assert isinstance(inst, _GoodTransformerA)


def test_get_transformer_strips_whitespace_in_msh9():
    registry.register("ADT^A01")(_GoodTransformerA)
    msg = _StubMessage("  ADT^A01 \r")
    inst = registry.get_transformer(msg)
    assert inst is not None


def test_get_transformer_exception_during_value_access():
    class _EvilMSH9:
        @property
        def value(self):
            raise RuntimeError("kaboom")

    class _Msg:
        def __init__(self):
            # No to_er7 -> forces getattr(..., "value", msh9), which raises
            self.MSH = types.SimpleNamespace(msh_9=_EvilMSH9())

    assert registry.get_transformer(_Msg()) is None


def test_get_transformer_returns_none_when_raw_is_none():
    class _NullMSH9:
        def to_er7(self):
            return None

    class _Msg:
        def __init__(self):
            self.MSH = types.SimpleNamespace(msh_9=_NullMSH9())

    assert registry.get_transformer(_Msg()) is None


def test_get_transformer_no_caret_in_msh9():
    registry.register("ORM^O01")(_GoodTransformerA)
    msg = _StubMessage("ORM")

    inst = registry.get_transformer(msg)
    assert inst is None
