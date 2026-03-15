"""Execute doctest suites for the LoopGraph package."""

from __future__ import annotations

import doctest

import loopgraph
import loopgraph._debug as debug_module
import loopgraph.bus.eventbus as eventbus_module
import loopgraph.concurrency.policies as policies_module
import loopgraph.diagnostics.inspect as diagnostics_module
import loopgraph.persistence.event_log as event_log_module
import loopgraph.persistence.snapshot as snapshot_module
import loopgraph.registry.function_registry as registry_module
import loopgraph.scheduler.scheduler as scheduler_module
from loopgraph import log_loop_iteration, log_parameter, log_variable_change
from loopgraph.core import graph as graph_module
from loopgraph.core import state as state_module
from loopgraph.core import types as types_module


def test_doctests() -> None:
    """Ensure documentation examples stay in sync with code."""
    func_name = "test_doctests"
    log_parameter(func_name)
    modules = [
        loopgraph,
        debug_module,
        graph_module,
        types_module,
        state_module,
        eventbus_module,
        policies_module,
        registry_module,
        scheduler_module,
        event_log_module,
        snapshot_module,
        diagnostics_module,
    ]
    log_variable_change(func_name, "modules", modules)
    for iteration, module in enumerate(modules):
        log_loop_iteration(func_name, "modules", iteration)
        result = doctest.testmod(module, optionflags=doctest.ELLIPSIS)
        log_variable_change(func_name, "result", result)
        assert result.failed == 0
