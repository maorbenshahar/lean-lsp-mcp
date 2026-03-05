"""Goal tracker: find sorry dependencies in a declaration's transitive closure.

Mirrors the tree output of QuantumInformation/scripts/goal_tracker.py but
runs entirely via LSP (no ExportDecls, no oleans needed).  The Lean
``run_cmd`` block BFS-walks only sorry-tainted dependencies using
``collectAxioms`` as an oracle, then emits one line per sorry node so that
Python can reconstruct the tree.

Key optimisation: instead of walking ALL transitive dependencies (which
explodes into Mathlib with 10,000+ nodes), each dependency is first checked
via ``Lean.collectAxioms``.  Only deps whose axiom closure includes
``sorryAx`` are followed.  This keeps the visited set tiny — typically
single-digit to low-dozens — regardless of how many Mathlib constants the
declaration references.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Lean snippet
# ---------------------------------------------------------------------------

def make_sorry_snippet(decl_name: str) -> str:
    """Return a ``run_cmd`` block that BFS-walks sorry-tainted deps.

    Uses ``Lean.collectAxioms`` as a fast oracle to prune the BFS: only
    dependencies whose axiom closure includes ``sorryAx`` are followed.
    This avoids walking into Mathlib/stdlib entirely.

    Output format (one ``logInfo`` per sorry-tainted node)::

        MCP_NODE:<json>

    where *json* is ``{{"name":..., "explicit":bool, "sorry_deps":[...],
    "module":str|null, "line":int|null}}``.  ``module`` and ``line`` are
    emitted for nodes with ``explicit=true`` so callers can locate sorry
    leaves without a separate search.

    A final summary line is emitted as::

        MCP_SUMMARY:<json>

    with ``{{"visited":int}}``.
    """
    return f"""
open Lean Lean.Elab.Command in
#eval show CommandElabM Unit from do
  let env ← getEnv
  let mkN (n : Name) (s : String) : Name := if let some k := s.toNat? then n.num k else n.str s
  let target : Name := "{decl_name}".splitOn "." |>.foldl mkN .anonymous
  if (env.find? target).isNone then throwError "not found: {decl_name}"
  -- Quick check: does target have sorryAx at all?
  let targetAxioms ← Lean.collectAxioms target
  if !targetAxioms.contains ``sorryAx then
    -- Clean declaration — emit summary only
    let summary := Json.mkObj [("visited", Json.num 1)]
    logInfo m!"MCP_SUMMARY:{{summary.compress}}"
  else
    -- BFS only through sorry-tainted deps (collectAxioms as oracle)
    let mut visited : NameSet := .empty
    let mut queue : Array Name := #[target]
    let mut nodeInfo : Array (Name × Bool × Array Name) := #[]
    let mut axCache : PersistentHashMap Name (Array Name) := .empty
    axCache := axCache.insert target targetAxioms
    while queue.size > 0 do
      let name := queue.back!
      queue := queue.pop
      if visited.contains name then continue
      visited := visited.insert name
      if (env.find? name).isNone then continue
      let ci := (env.find? name).get!
      let allConsts := ci.getUsedConstantsAsSet
      let explicit := allConsts.contains ``sorryAx
      let mut sorryDeps : Array Name := #[]
      for dep in allConsts.toArray do
        if dep == ``sorryAx then continue
        if (env.find? dep).isNone then continue
        let depAxioms ← match axCache.find? dep with
          | some ax => pure ax
          | none => do
            let ax ← Lean.collectAxioms dep
            axCache := axCache.insert dep ax
            pure ax
        if depAxioms.contains ``sorryAx then
          sorryDeps := sorryDeps.push dep
          if !visited.contains dep then
            queue := queue.push dep
      nodeInfo := nodeInfo.push (name, explicit, sorryDeps)
    -- Emit one line per sorry-tainted node
    for (name, explicit, sorryDeps) in nodeInfo do
      -- For explicit sorry nodes, resolve module + line so callers can locate them
      let mut fields : Array (String × Json) := #[
        ("name", Json.str name.toString),
        ("explicit", Json.bool explicit),
        ("sorry_deps", Json.arr (sorryDeps.map fun d => Json.str d.toString))
      ]
      if explicit then
        match env.getModuleFor? name with
        | some mod => fields := fields.push ("module", Json.str mod.toString)
        | none => pure ()
        match ← findDeclarationRanges? name with
        | some ranges => fields := fields.push ("line", Json.num ranges.range.pos.line)
        | none => pure ()
      logInfo m!"MCP_NODE:{{(Json.mkObj fields.toList).compress}}"
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
    module: str | None = None
    line: int | None = None


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
            line_num = obj.get("line")
            nodes[name] = SorryNode(
                name=name,
                explicit_sorry=obj.get("explicit", False),
                sorry_deps=obj.get("sorry_deps", []),
                module=obj.get("module"),
                line=int(line_num) if line_num is not None else None,
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
