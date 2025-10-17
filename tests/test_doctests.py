"""Execute doctest suites for the EventFlow package."""

from __future__ import annotations

import doctest

import eventflow
import eventflow._debug as debug_module
import eventflow.bus.eventbus as eventbus_module
import eventflow.concurrency.policies as policies_module
import eventflow.registry.function_registry as registry_module
import eventflow.scheduler.scheduler as scheduler_module
from eventflow import log_loop_iteration, log_parameter, log_variable_change
from eventflow.core import graph as graph_module
from eventflow.core import state as state_module
from eventflow.core import types as types_module


def test_doctests() -> None:
    """Ensure documentation examples stay in sync with code."""
    func_name = "test_doctests"
    log_parameter(func_name)
    modules = [
        eventflow,
        debug_module,
        graph_module,
        types_module,
        state_module,
        eventbus_module,
        policies_module,
        registry_module,
        scheduler_module,
    ]
    log_variable_change(func_name, "modules", modules)
    for iteration, module in enumerate(modules):
        log_loop_iteration(func_name, "modules", iteration)
        result = doctest.testmod(module, optionflags=doctest.ELLIPSIS)
        log_variable_change(func_name, "result", result)
        assert result.failed == 0
