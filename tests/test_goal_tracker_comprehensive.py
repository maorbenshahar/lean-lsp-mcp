"""Comprehensive comparison: lean_verify vs lean_goal_tracker vs ground truth.

Ground truth from `#print axioms` via `lake env lean`:

  gt_clean              -> [propext]                      (no sorry)
  gt_direct_sorry       -> [sorryAx]                      (direct sorry)
  gt_helper             -> no axioms                      (clean def)
  gt_uses_clean_helper  -> no axioms                      (clean thm using clean def)
  gt_sorry_def          -> [sorryAx]                      (sorry in def)
  gt_transitive_sorry   -> [sorryAx]                      (sorry def + sorry proof)
  gt_level2_sorry       -> [sorryAx]                      (sorry def, depth 2)
  gt_level1             -> [sorryAx]                      (depends on sorry def)
  gt_chain_sorry        -> [sorryAx]                      (2-level chain)
  gt_decidable          -> no axioms                      (clean)
  gt_noncomputable      -> [Classical.choice]             (no sorry, has axiom)
  gt_uses_noncomputable -> [Classical.choice]             (transitive axiom, no sorry)
  gt_term_sorry         -> [sorryAx]                      (term-mode sorry)
  gt_uses_term_sorry    -> [sorryAx]                      (transitive term sorry)
  gt_sorry_a            -> [sorryAx]                      (sorry)
  gt_sorry_b            -> [sorryAx]                      (sorry)
  gt_multi_sorry        -> [sorryAx]                      (multiple sorry sources)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import AsyncContextManager

import pytest

from tests.helpers.mcp_client import MCPClient, result_json


# Ground truth: does #print axioms report sorryAx?
GROUND_TRUTH = {
    # (has_sorry_in_axioms, expected_sorry_decls_subset, description)
    "gt_clean":              (False, [],                          "clean theorem, standard axioms only"),
    "gt_direct_sorry":       (True,  ["gt_direct_sorry"],         "direct sorry in proof"),
    "gt_helper":             (False, [],                          "clean def, no axioms"),
    "gt_uses_clean_helper":  (False, [],                          "clean theorem using clean def"),
    "gt_sorry_def":          (True,  ["gt_sorry_def"],            "sorry in def body"),
    "gt_transitive_sorry":   (True,  ["gt_transitive_sorry", "gt_sorry_def"], "sorry def + sorry proof"),
    "gt_level2_sorry":       (True,  ["gt_level2_sorry"],         "sorry def at depth 2"),
    "gt_level1":             (True,  ["gt_level2_sorry"],         "depends on sorry def transitively"),
    "gt_chain_sorry":        (True,  ["gt_level2_sorry"],         "2-level chain to sorry"),
    "gt_decidable":          (False, [],                          "decidable, no sorry"),
    "gt_noncomputable":      (False, [],                          "Classical.choice axiom, no sorry"),
    "gt_uses_noncomputable": (False, [],                          "transitive axiom, no sorry"),
    "gt_term_sorry":         (True,  ["gt_term_sorry"],           "term-mode sorry"),
    "gt_uses_term_sorry":    (True,  ["gt_term_sorry"],           "transitive term-mode sorry"),
    "gt_sorry_a":            (True,  ["gt_sorry_a"],              "sorry source A"),
    "gt_sorry_b":            (True,  ["gt_sorry_b"],              "sorry source B"),
    "gt_multi_sorry":        (True,  ["gt_sorry_a", "gt_sorry_b"], "multiple sorry sources converging"),
    "gt_diamond":            (True,  ["gt_shared_sorry"],          "diamond: shared sorry dep via two paths"),
    "GtNs.ns_clean":         (False, [],                          "namespaced clean theorem"),
    "GtNs.ns_sorry":         (True,  ["GtNs.ns_sorry"],           "namespaced sorry theorem"),
    "GtNs.ns_uses_private":  (True,  [],                          "uses private sorry def transitively"),
    "GtOuter.GtInner.nested_sorry": (True, ["GtOuter.GtInner.nested_sorry"], "nested namespace sorry"),
    "gt_in_section":         (False, [],                          "theorem in section, no namespace effect"),
}


@pytest.mark.asyncio
async def test_verify_matches_ground_truth(
    mcp_client_factory: Callable[[], AsyncContextManager[MCPClient]],
    test_project_path: Path,
) -> None:
    """lean_verify: sorryAx in axioms iff ground truth says sorry."""
    gt_file = test_project_path / "GoalTrackerTest.lean"
    async with mcp_client_factory() as client:
        for decl, (has_sorry, _, desc) in GROUND_TRUTH.items():
            result = await client.call_tool(
                "lean_verify",
                {"file_path": str(gt_file), "theorem_name": decl, "scan_source": False},
            )
            data = result_json(result)
            axioms = data["axioms"]
            got_sorry = "sorryAx" in axioms
            assert got_sorry == has_sorry, (
                f"lean_verify {decl} ({desc}): "
                f"expected sorry={has_sorry}, got axioms={axioms}"
            )


@pytest.mark.asyncio
async def test_goal_tracker_matches_ground_truth(
    mcp_client_factory: Callable[[], AsyncContextManager[MCPClient]],
    test_project_path: Path,
) -> None:
    """lean_goal_tracker: sorry_declarations empty iff no sorry in ground truth."""
    gt_file = test_project_path / "GoalTrackerTest.lean"
    async with mcp_client_factory() as client:
        for decl, (has_sorry, expected_decls, desc) in GROUND_TRUTH.items():
            result = await client.call_tool(
                "lean_goal_tracker",
                {"file_path": str(gt_file), "decl_name": decl},
            )
            data = result_json(result)
            sorry_decls = data["sorry_declarations"]

            if has_sorry:
                assert len(sorry_decls) >= 1, (
                    f"goal_tracker {decl} ({desc}): expected sorry_declarations non-empty, got {data}"
                )
                for ed in expected_decls:
                    assert ed in sorry_decls, (
                        f"goal_tracker {decl} ({desc}): "
                        f"expected '{ed}' in sorry_declarations={sorry_decls}"
                    )
            else:
                assert sorry_decls == [], (
                    f"goal_tracker {decl} ({desc}): expected no sorry, got {data}"
                )

            assert data["total_transitive_deps"] > 0, (
                f"goal_tracker {decl} ({desc}): expected deps > 0, got {data}"
            )


@pytest.mark.asyncio
async def test_goal_tracker_short_name_resolution(
    mcp_client_factory: Callable[[], AsyncContextManager[MCPClient]],
    test_project_path: Path,
) -> None:
    """goal_tracker resolves short names to FQNs via namespace scanning."""
    gt_file = test_project_path / "GoalTrackerTest.lean"
    async with mcp_client_factory() as client:
        # Short name "ns_sorry" should resolve to GtNs.ns_sorry
        result = await client.call_tool(
            "lean_goal_tracker",
            {"file_path": str(gt_file), "decl_name": "ns_sorry"},
        )
        data = result_json(result)
        assert data["target"] == "ns_sorry"
        assert len(data["sorry_declarations"]) >= 1
        assert data["total_transitive_deps"] > 0


@pytest.mark.asyncio
async def test_goal_tracker_nonexistent_short_name(
    mcp_client_factory: Callable[[], AsyncContextManager[MCPClient]],
    test_project_path: Path,
) -> None:
    """Short name that doesn't exist in the file — error."""
    gt_file = test_project_path / "GoalTrackerTest.lean"
    async with mcp_client_factory() as client:
        result = await client.call_tool(
            "lean_goal_tracker",
            {"file_path": str(gt_file), "decl_name": "totally_nonexistent_xyz"},
            expect_error=True,
        )
        assert result.isError


@pytest.mark.asyncio
async def test_goal_tracker_section_no_namespace_effect(
    mcp_client_factory: Callable[[], AsyncContextManager[MCPClient]],
    test_project_path: Path,
) -> None:
    """Theorem in a section — FQN should not include section name."""
    gt_file = test_project_path / "GoalTrackerTest.lean"
    async with mcp_client_factory() as client:
        result = await client.call_tool(
            "lean_goal_tracker",
            {"file_path": str(gt_file), "decl_name": "gt_in_section"},
        )
        data = result_json(result)
        assert data["target"] == "gt_in_section"
        assert data["sorry_declarations"] == []
        assert data["total_transitive_deps"] > 0


@pytest.mark.asyncio
async def test_verify_and_tracker_agree(
    mcp_client_factory: Callable[[], AsyncContextManager[MCPClient]],
    test_project_path: Path,
) -> None:
    """lean_verify (sorryAx in axioms) should agree with lean_goal_tracker (fully_proven)."""
    gt_file = test_project_path / "GoalTrackerTest.lean"
    async with mcp_client_factory() as client:
        for decl in GROUND_TRUTH:
            verify_result = await client.call_tool(
                "lean_verify",
                {"file_path": str(gt_file), "theorem_name": decl, "scan_source": False},
            )
            tracker_result = await client.call_tool(
                "lean_goal_tracker",
                {"file_path": str(gt_file), "decl_name": decl},
            )
            v_data = result_json(verify_result)
            t_data = result_json(tracker_result)

            v_has_sorry = "sorryAx" in v_data["axioms"]
            t_has_sorry = len(t_data["sorry_declarations"]) > 0

            assert v_has_sorry == t_has_sorry, (
                f"{decl}: verify says sorry={v_has_sorry} "
                f"(axioms={v_data['axioms']}), "
                f"tracker says sorry={t_has_sorry} "
                f"(sorry_decls={t_data['sorry_declarations']})"
            )
