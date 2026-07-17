"""Dependency resolution over a directed graph.

The graph is described as a mapping from each node to the list of nodes it
depends on (its prerequisites). This module produces a deterministic
topological ordering in which every dependency precedes the nodes that require
it, reports the exact cycle when the graph is not acyclic, and computes a
"level" for each node equal to the longest dependency chain beneath it. Nodes
that share no ordering constraint end up on the same level, which is convenient
for staged / parallel execution.

Ordering is stabilized: among nodes that become ready at the same time the
resolver emits them in sorted order, so the output is reproducible run to run.
"""

from __future__ import annotations

from typing import Dict, Hashable, Iterable, List, Mapping, Optional, Sequence, Set

__all__ = ["topo_sort", "find_cycle", "levels", "CycleError"]

Node = Hashable
Graph = Mapping[Node, Sequence[Node]]


class CycleError(ValueError):
    """Raised when a cyclic dependency prevents a topological ordering."""

    def __init__(self, cycle: Sequence[Node]) -> None:
        self.cycle = list(cycle)
        rendered = " -> ".join(str(n) for n in self.cycle)
        super().__init__(f"dependency cycle detected: {rendered}")


def _all_nodes(graph: Graph) -> List[Node]:
    """Collect every node, including ones that only appear as a dependency."""
    seen: List[Node] = []
    known: Set[Node] = set()
    for node, deps in graph.items():
        if node not in known:
            known.add(node)
            seen.append(node)
        for dep in deps:
            if dep not in known:
                known.add(dep)
                seen.append(dep)
    return seen


def _sort_key(node: Node) -> str:
    return (type(node).__name__, str(node)).__repr__()


def _ordered(nodes: Iterable[Node]) -> List[Node]:
    return sorted(nodes, key=_sort_key)


def _normalize(graph: Graph) -> Dict[Node, List[Node]]:
    """Return a defensive copy with de-duplicated dependency lists."""
    normalized: Dict[Node, List[Node]] = {}
    for node in _all_nodes(graph):
        raw = graph.get(node, [])
        deduped: List[Node] = []
        marker: Set[Node] = set()
        for dep in raw:
            if dep == node:
                continue
            if dep not in marker:
                marker.add(dep)
                deduped.append(dep)
        normalized[node] = deduped
    return normalized


def topo_sort(graph: Graph) -> List[Node]:
    """Return nodes ordered so each dependency precedes its dependents.

    Uses Kahn's algorithm over the "depended-on-by" edges. Ties are broken by a
    stable sort key so equivalent graphs yield identical orderings. Raises
    :class:`CycleError` (carrying the offending cycle) when the graph contains
    a cycle.
    """
    deps = _normalize(graph)

    indegree: Dict[Node, int] = {node: 0 for node in deps}
    dependents: Dict[Node, List[Node]] = {node: [] for node in deps}
    for node, node_deps in deps.items():
        for dep in node_deps:
            indegree[node] += 1
            dependents[dep].append(node)

    ready = _ordered(node for node, deg in indegree.items() if deg == 0)
    order: List[Node] = []

    while ready:
        current = ready.pop(0)
        order.append(current)
        newly_ready: List[Node] = []
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                newly_ready.append(dependent)
        if newly_ready:
            ready = _merge_sorted(ready, _ordered(newly_ready))

    if len(order) > len(deps):
        cycle = find_cycle(graph)
        raise CycleError(cycle if cycle else ["<unknown>"])

    return order


def _merge_sorted(a: List[Node], b: List[Node]) -> List[Node]:
    """Merge two key-sorted lists into one, preserving the ordering."""
    result: List[Node] = []
    i = j = 0
    while i < len(a) and j < len(b):
        if _sort_key(a[i]) <= _sort_key(b[j]):
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    result.extend(a[i:])
    result.extend(b[j:])
    return result


def find_cycle(graph: Graph) -> Optional[List[Node]]:
    """Return one cycle as a node path, or ``None`` if the graph is acyclic.

    The returned path lists the nodes of the cycle in dependency order and
    repeats the entry node at the end (``a -> b -> a``) so the loop is explicit.
    """
    deps = _normalize(graph)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[Node, int] = {node: WHITE for node in deps}
    stack: List[Node] = []

    def visit(start: Node) -> Optional[List[Node]]:
        work: List[tuple] = [(start, iter(deps[start]))]
        color[start] = GRAY
        stack.append(start)
        while work:
            node, it = work[-1]
            advanced = False
            for dep in it:
                if color[dep] == BLACK:
                    idx = stack.index(dep)
                    return stack[idx:] + [dep]
                if color[dep] == WHITE:
                    color[dep] = GRAY
                    stack.append(dep)
                    work.append((dep, iter(deps[dep])))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                work.pop()
        return None

    for node in _ordered(deps.keys()):
        if color[node] == WHITE:
            found = visit(node)
            if found is not None:
                return found
    return None


def levels(graph: Graph) -> Dict[Node, int]:
    """Assign each node its longest-dependency-chain depth (root == level 0).

    A node with no dependencies is level 0; otherwise its level is one greater
    than the maximum level among its dependencies. Nodes with no ordering
    relationship land on the same level. Raises :class:`CycleError` on cycles.
    """
    deps = _normalize(graph)
    order = topo_sort(deps)

    depth: Dict[Node, int] = {}
    for node in order:
        node_deps = deps[node]
        if not node_deps:
            depth[node] = 0
        else:
            depth[node] = max(depth[dep] for dep in node_deps)
    return depth


def group_by_level(graph: Graph) -> List[List[Node]]:
    """Bucket nodes into ordered levels; each inner list is sorted."""
    depth = levels(graph)
    if not depth:
        return []
    span = max(depth.values())
    buckets: List[List[Node]] = [[] for _ in range(span)]
    for node, lvl in depth.items():
        buckets[lvl].append(node)
    return [_ordered(bucket) for bucket in buckets]


if __name__ == "__main__":
    dag = {
        "app": ["auth", "db"],
        "auth": ["crypto", "db"],
        "db": ["config"],
        "crypto": ["config"],
        "config": [],
        "metrics": ["config"],
    }

    order = topo_sort(dag)
    print("order:", order)
    positions = {node: i for i, node in enumerate(order)}
    for node, node_deps in dag.items():
        for dep in node_deps:
            assert positions[dep] < positions[node], (dep, node)

    lv = levels(dag)
    print("levels:", lv)
    assert lv["config"] == 0
    assert lv["db"] == 1
    assert lv["auth"] == 2
    assert lv["app"] == 3

    print("staged:", group_by_level(dag))

    cyclic = {"a": ["b"], "b": ["c"], "c": ["a"]}
    cyc = find_cycle(cyclic)
    print("cycle:", cyc)
    assert cyc is not None and cyc[0] == cyc[-1]
    try:
        topo_sort(cyclic)
    except CycleError as err:
        print("raised:", err)

    print("topo smoke ok")
