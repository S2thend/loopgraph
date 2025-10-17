"""Utilities to standardise verbose debug logging across the codebase."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger("eventflow")


def log_parameter(func_name: str, **params: Any) -> None:
    """Log each parameter passed into a function.

    >>> log_parameter("demo_func", alpha=1, beta="two")
    """
    LOGGER.debug("function=%s parameters=%r", func_name, params)


def log_variable_change(func_name: str, name: str, value: Any) -> None:
    """Log a variable change to comply with the DevSOP rules.

    >>> log_variable_change("demo_func", "counter", 10)
    """
    LOGGER.debug("function=%s variable=%s value=%r", func_name, name, value)


def log_branch(func_name: str, branch: str) -> None:
    """Log which branch of conditional logic is being executed.

    >>> log_branch("demo_func", "if_true")
    """
    LOGGER.debug("function=%s branch=%s", func_name, branch)


def log_loop_iteration(func_name: str, loop_name: str, iteration: int) -> None:
    """Log loop iteration counts to support replay-friendly diagnostics.

    >>> log_loop_iteration("demo_func", "main", 3)
    """
    LOGGER.debug(
        "function=%s loop=%s iteration=%d",
        func_name,
        loop_name,
        iteration,
    )
