from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4


class SearchTrace:
    """Bounded capture of real search events; omitted entirely for ordinary runs."""

    def __init__(self, *, max_nodes: int = 300):
        self.trace_id = str(uuid4())
        self.max_nodes = max(1, min(int(max_nodes), 1000))
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self._id = 0
        self.truncated = False

    def record(self, event: str, state: dict, *, parent_id: int | None = None, action: dict | None = None, depth: int = 0, g: float | None = None, h: float | None = None, f: float | None = None, reason: str | None = None) -> int | None:
        if len(self.nodes) >= self.max_nodes:
            self.truncated = True
            return None
        node_id = self._id
        self._id += 1
        node = {
            "id": node_id, "parent_id": parent_id, "event": event,
            "depth": depth, "g": _round(g), "h": _round(h), "f": _round(f),
            "action": action, "reason": reason,
            "placements": [{"operation_id": key, **value} for key, value in sorted(state.items())],
        }
        self.nodes.append(node)
        if parent_id is not None:
            self.edges.append({"source": parent_id, "target": node_id})
        return node_id


class TraceStore:
    def __init__(self, *, ttl_seconds: int = 1800, max_traces: int = 128):
        self.ttl_seconds = ttl_seconds
        self.max_traces = max_traces
        self._items: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = RLock()

    def put(self, trace_id: str, payload: dict) -> None:
        with self._lock:
            self._purge()
            self._items[trace_id] = (monotonic(), payload)
            self._items.move_to_end(trace_id)
            while len(self._items) > self.max_traces:
                self._items.popitem(last=False)

    def get(self, trace_id: str) -> dict | None:
        with self._lock:
            self._purge()
            item = self._items.get(trace_id)
            if item is None:
                return None
            self._items.move_to_end(trace_id)
            return item[1]

    def latest(self) -> dict | None:
        with self._lock:
            self._purge()
            return next(reversed(self._items.values()))[1] if self._items else None

    def _purge(self) -> None:
        now = monotonic()
        for key, (created, _) in list(self._items.items()):
            if now - created > self.ttl_seconds:
                self._items.pop(key, None)


def _round(value):
    return None if value is None else round(float(value), 6)


trace_store = TraceStore()

def finalize_trace(trace: SearchTrace, result: dict, *, dataset_source: str, scenario: str, objective: str, algorithm: str) -> dict:
    payload = {
        "trace_id": trace.trace_id, "algorithm": algorithm, "scenario": scenario,
        "objective": objective, "dataset_source": dataset_source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "nodes": trace.nodes, "edges": trace.edges, "truncated": trace.truncated,
        "result": result,
    }
    trace_store.put(trace.trace_id, payload)
    return payload
