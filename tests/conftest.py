# tests/conftest.py
# Silences Conda warnings during test runs without requiring user config.
import warnings
import logging


def pytest_configure(config):
    warnings.filterwarnings(
        "ignore",
        message=r"Adding 'defaults' to channel list implicitly is deprecated.*",
        category=FutureWarning,
        module=r"conda\.base\.context",
    )

    logging.getLogger("conda.cli.main_config").setLevel(logging.ERROR)
    logging.getLogger("conda.base.context").setLevel(logging.ERROR)

    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        module=r"conda\..*",
    )
