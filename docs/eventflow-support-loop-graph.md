 还写了 “Eventflow changes identified: No”：specs/010-unified-graph-loop/spec.md:283
    - 但 plan 明确说必须改 eventflow scheduler：specs/010-unified-graph-loop/plan.md:10
    - plan 还标注了这条冲突：specs/010-unified-graph-loop/plan.md:61

  选项。
• Explored
  └ Read research.md, plan.md, scheduler.py, state.py
    Search def is_ready|def mark_complete|def mark_running|class ExecutionState in scheduler
    Search class ExecutionState|def is_ready|def mark_complete|def mark_running in eventflow
    Read state.py, test_integration_workflows.py

• 你这个追问很关键。给你基于现有代码证据的背景：

  为什么要改 eventflow
  - 但 scheduler 目前“只跑一次节点”：
      - run() 初始化 pending 后循环执行，节点完成后直接 pending.remove(node_id)（../eventflow/eventflow/scheduler/
      - 节点完成会被标记为 COMPLETED（../eventflow/eventflow/scheduler/scheduler.py:246，../eventflow/eventflow/core/state.py:300）。
      - is_ready() 只有 PENDING 才可调度（../eventflow/eventflow/core/state.py:196）。
  - 虽然 SWITCH 能选到回边（../eventflow/eventflow/scheduler/scheduler.py:357-364），但当前逻辑只 note_upstream_completion，不会把目
    标节点重新放回 pending（../eventflow/eventflow/scheduler/scheduler.py:272）。
  - 现有 eventflow 测试也在“手工重置状态”来模拟 loop（../eventflow/tests/test_integration_workflows.py:176-186），反向证明调度器没原


  - 改点就在 scheduler：
      - 在 _execute_node 选出 downstream edges 后（../eventflow/eventflow/scheduler/scheduler.py:260-267），对命中的回边目标做 re-
        entry：
          2. execution_state._completed_nodes.discard(target)
          3. 把 target 重新加入 pending
  - 这需要把 pending 传进 _execute_node，或让 _execute_node 返回“需要重排队的节点”（specs/010-unified-graph-loop/plan.md:193-200）。
  - 再补一个 e2e：真实 Scheduler.run() 下 loop 节点按 max_visits 执行 N 次，不再手工改 state（对应 tasks 的 T004 方向）。

  不改 eventflow 行不行

  - 行，但代价大：
      - 在 core 包装 scheduler（复杂且脆弱，重复调度内部语义）。
      - 或回退到 SDK 外层 while（会与当前图内 loop 目标/constitution 方向冲突）。
  - 所以 plan 才给了“改 eventflow 是最小可控改动”的结论（specs/010-unified-graph-loop/research.md:116-125）。

  基于这些背景，C2 你选哪个：

  - B：不改 eventflow，改成 core workaround

› A 而且我们还需要在eventflow支持回环次数（PENDING）


■ Conversation interrupted - tell the model what to do differently. Something went wrong? Hit `/feedback` to report the issue.


› A 而且我们还需要在eventflow支持回环次数（PENDING重置次数）允许completed被调度时重回PENDING


• 收到，记录 C2 结论：

  - 选 A（允许 eventflow 源码改动，走显式审批）
  - 你补充的强约束也记录：
      1. 需要支持回环重入计数（PENDING 重置次数）
      2. 允许目标节点在 COMPLETED 状态下被重新调度为 PENDING（受 max_visits 约束）

---

## 实现方案

### 问题根因

scheduler 当前只跑一次节点。三个卡点：

1. `run()` 中 `pending.remove(node_id)` 永久移除节点（scheduler.py:184）
2. `mark_complete()` 设 status=COMPLETED 并加入 `_completed_nodes`（state.py:300-308）
3. `is_ready()` 拒绝非 PENDING 节点（state.py:196）

### 改动清单（3 个文件）

#### 1. `eventflow/core/state.py` — 新增 `reset_for_reentry()`

在 `note_upstream_completion()` 之后（约 line 354）加一个方法：

```python
def reset_for_reentry(self, node_id: str) -> None:
    """Reset a completed node to PENDING for re-scheduling (loop back-edge)."""
    state = self._ensure_state(node_id)
    state.status = NodeStatus.PENDING
    state.upstream_completed.clear()
    self._completed_nodes.discard(node_id)
```

关键点：**不重置 `visits.count`**。count 持续累加，`max_visits` 靠它限流。

#### 2. `eventflow/scheduler/scheduler.py` — 两处改动

**改动 A：`_execute_node` 返回 re-entry 目标**

当前签名返回 `Any`，改为返回 `Tuple[Any, List[str]]`（handler result + 需要重排队的 node_id 列表）。

在现有 downstream edge 处理循环（line 267-272）之后，加：

```python
reentry_targets: List[str] = []
for edge in selected_edges:
    target = edge.target
    target_state = execution_state._ensure_state(target)
    if (target_state.status == NodeStatus.COMPLETED
            and self._has_remaining_visits(graph, execution_state, target)):
        execution_state.reset_for_reentry(target)
        reentry_targets.append(target)
```

方法结尾 `return result` 改为 `return result, reentry_targets`。

**改动 B：`run()` 消费 re-entry 目标**

调用处（line 174）改为解包：

```python
handler_result, reentry_targets = await self._execute_node(...)
```

在 `pending.remove(node_id)` 之后加：

```python
for target in reentry_targets:
    pending.add(target)
```

这样主循环的下一轮迭代会看到被重新加入的节点并调度它。

#### 3. `tests/test_integration_workflows.py` — 更新 + 新增测试

**更新 `test_loop_respects_max_visits`**：把手工 reset（line 183-185）替换为 `state.reset_for_reentry("loop")`。

**新增 `test_scheduler_loop_reentry_e2e`**：真实 `Scheduler.run()` 跑完整 loop：

```
start → loop_body → switch
                      ↓ route="continue" → loop_body（回边）
                      ↓ route="done" → output
```

- `loop_body`: `max_visits=3`, `allow_partial_upstream=True`
- `switch` handler: 前 2 次返回 "continue"，第 3 次返回 "done"
- 断言：loop_body 执行 3 次，output 执行 1 次
- 断言：event log 中 NODE_SCHEDULED / NODE_COMPLETED 数量正确

### 验证

```bash
cd /Users/borui/Devs/open-source-general-agents/wormhole/eventflow
python -m pytest tests/ -v
```

全量现有测试通过 + 新 e2e 测试通过。
