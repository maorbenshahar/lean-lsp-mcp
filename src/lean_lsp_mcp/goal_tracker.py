"""Goal tracker: find sorry dependencies in a declaration's transitive closure.

Mirrors the tree output of QuantumInformation/scripts/goal_tracker.py but
runs entirely via LSP (no ExportDecls, no oleans needed).  The Lean
``run_cmd`` block BFS-walks the environment, collecting every declaration
whose transitive closure touches ``sorryAx``, then emits one line per
sorry-tainted node so that Python can reconstruct the tree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Lean snippet
# ---------------------------------------------------------------------------

def make_sorry_snippet(decl_name: str) -> str:
    """Return a ``run_cmd`` block that BFS-walks transitive deps for sorry.

    Output format (one ``logInfo`` per sorry-tainted node)::

        MCP_NODE:<json>

    where *json* is ``{{"name":..., "explicit":bool, "sorry_deps":[...]}}``.
    A final summary line is emitted as::

        MCP_SUMMARY:<json>

    with ``{{"visited":int}}``.
    """
    return f"""
set_option maxHeartbeats 800000
open Lean Lean.Elab.Command in
#eval show CommandElabM Unit from do
  let env ← getEnv
  let mkN (n : Name) (s : String) : Name := if let some k := s.toNat? then n.num k else n.str s
  let target : Name := "{decl_name}".splitOn "." |>.foldl mkN .anonymous
  if (env.find? target).isNone then throwError "not found: {decl_name}"
  -- BFS: compute visited set and per-node direct constants
  let mut visited : NameSet := .empty
  let mut queue : Array Name := #[target]
  -- Store (name, directlyContainsSorryAx, depsArray) per visited node
  let mut nodeInfo : Array (Name × Bool × Array Name) := #[]
  while queue.size > 0 do
    let name := queue.back!
    queue := queue.pop
    if visited.contains name then continue
    visited := visited.insert name
    if (env.find? name).isNone then continue
    let ci := (env.find? name).get!
    let allConsts := ci.getUsedConstantsAsSet
    let depsArr := allConsts.toArray
    let explicit := allConsts.contains ``sorryAx
    nodeInfo := nodeInfo.push (name, explicit, depsArr)
    for dep in depsArr do
      if !visited.contains dep then
        queue := queue.push dep
  -- Backward pass: compute transitive sorry status with memoisation
  let mut hasSorryMap : NameMap Bool := .empty
  -- Seed: any node that directly contains sorryAx is sorry
  for (name, explicit, _) in nodeInfo do
    if explicit then hasSorryMap := hasSorryMap.insert name true
  -- Fixed-point iteration (cheap – nodeInfo is small)
  let mut changed := true
  while changed do
    changed := false
    for (name, _, deps) in nodeInfo do
      if (hasSorryMap.find? name).getD false then continue
      for dep in deps do
        if (hasSorryMap.find? dep).getD false then
          hasSorryMap := hasSorryMap.insert name true
          changed := true
          break
  -- Emit one line per sorry-tainted node
  for (name, explicit, deps) in nodeInfo do
    unless (hasSorryMap.find? name).getD false do continue
    let mut sorryChildren : Array String := #[]
    for dep in deps do
      if dep == ``sorryAx then continue
      if (hasSorryMap.find? dep).getD false then
        sorryChildren := sorryChildren.push dep.toString
    let node := Json.mkObj [
      ("name", Json.str name.toString),
      ("explicit", Json.bool explicit),
      ("sorry_deps", Json.arr (sorryChildren.map Json.str))
    ]
    logInfo m!"MCP_NODE:{{node.compress}}"
  let summary := Json.mkObj [("visited", Json.num visited.size)]
  logInfo m!"MCP_SUMMARY:{{summary.compress}}"
"""


# ---------------------------------------------------------------------------
# Parse diagnostics
# ---------------------------------------------------------------------------

@dataclass
class SorryNode:
    """One declaration in the sorry-issue tree."""
    name: str
    explicit_sorry: bool = False
    sorry_deps: list[str] = field(default_factory=list)


def parse_sorry_result(diagnostics: list[dict]) -> tuple[dict[str, SorryNode], int]:
    """Parse MCP_NODE / MCP_SUMMARY lines from diagnostics.

    Returns (nodes_by_name, total_visited).
    """
    nodes: dict[str, SorryNode] = {}
    visited = 0

    for diag in diagnostics:
        if diag.get("severity") != 3:  # info
            continue
        msg = diag.get("message", "")
        if msg.startswith("MCP_NODE:"):
            raw = msg[len("MCP_NODE:"):]
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            name = obj["name"]
            nodes[name] = SorryNode(
                name=name,
                explicit_sorry=obj.get("explicit", False),
                sorry_deps=obj.get("sorry_deps", []),
            )
        elif msg.startswith("MCP_SUMMARY:"):
            raw = msg[len("MCP_SUMMARY:"):]
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            visited = obj.get("visited", 0)

    return nodes, visited


# ---------------------------------------------------------------------------
# Tree rendering  (mirrors goal_tracker.py print_issue_tree)
# ---------------------------------------------------------------------------

def render_tree(target: str, nodes: dict[str, SorryNode]) -> list[str]:
    """Render an ASCII dependency tree rooted at *target*.

    Only branches that lead to sorry are shown.  Each node is annotated
    with ``[explicit sorry]`` when the declaration itself contains
    ``sorryAx``.
    """
    lines: list[str] = []
    visited: set[str] = set()

    def _walk(name: str, prefix: str, is_last: bool) -> None:
        if name in visited:
            connector = "└─ " if is_last else "├─ "
            lines.append(f"{prefix}{connector}{name} (see above)")
            return
        visited.add(name)

        node = nodes.get(name)
        connector = "└─ " if is_last else "├─ "
        tag = " [explicit sorry]" if node and node.explicit_sorry else ""
        lines.append(f"{prefix}{connector}{name}{tag}")

        if node is None:
            return

        children = [d for d in node.sorry_deps if d in nodes]
        extension = "   " if is_last else "│  "
        new_prefix = prefix + extension
        for i, child in enumerate(children):
            _walk(child, new_prefix, i == len(children) - 1)

    _walk(target, "", True)
    return lines
