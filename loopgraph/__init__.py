"""LoopGraph package root exporting shared logging helpers."""

from __future__ import annotations

import logging

from ._debug import (
    log_branch,
    log_loop_iteration,
    log_parameter,
    log_variable_change,
)

__all__ = [
    "log_branch",
    "log_loop_iteration",
    "log_parameter",
    "log_variable_change",
]


def configure_default_logging(level: int = logging.DEBUG) -> None:
    """Configure a default logging handler for debugging heavy modules.

    >>> configure_default_logging()
    >>> logging.getLogger("loopgraph").getEffectiveLevel() == logging.DEBUG
    True
    """
    log_parameter("configure_default_logging", level=level)
    logging.basicConfig(level=level, force=True)
    logger = logging.getLogger("loopgraph")
    log_variable_change("configure_default_logging", "logger_level", logger.level)
    effective_level = logger.getEffectiveLevel()
    log_variable_change(
        "configure_default_logging",
        "effective_level",
        effective_level,
    )
