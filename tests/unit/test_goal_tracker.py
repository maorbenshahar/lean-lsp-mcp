"""Unit tests for goal_tracker module."""

from __future__ import annotations

from lean_lsp_mcp.goal_tracker import (
    SorryNode,
    make_sorry_snippet,
    parse_sorry_result,
    render_tree,
)


class TestMakeSorrySnippet:
    def test_contains_decl_name(self):
        snippet = make_sorry_snippet("Foo.bar")
        assert '"Foo.bar"' in snippet

    def test_contains_eval(self):
        snippet = make_sorry_snippet("myThm")
        assert "#eval" in snippet

    def test_contains_node_marker(self):
        snippet = make_sorry_snippet("myThm")
        assert "MCP_NODE" in snippet

    def test_contains_summary_marker(self):
        snippet = make_sorry_snippet("myThm")
        assert "MCP_SUMMARY" in snippet


class TestParseSorryResult:
    def test_no_sorry(self):
        diags = [{"severity": 3, "message": 'MCP_SUMMARY:{"visited":42}'}]
        nodes, visited = parse_sorry_result(diags)
        assert nodes == {}
        assert visited == 42

    def test_single_explicit(self):
        diags = [
            {"severity": 3, "message": 'MCP_NODE:{"name":"myThm","explicit":true,"sorry_deps":[]}'},
            {"severity": 3, "message": 'MCP_SUMMARY:{"visited":5}'},
        ]
        nodes, visited = parse_sorry_result(diags)
        assert "myThm" in nodes
        assert nodes["myThm"].explicit_sorry is True
        assert visited == 5

    def test_transitive_chain(self):
        diags = [
            {"severity": 3, "message": 'MCP_NODE:{"name":"A","explicit":false,"sorry_deps":["B"]}'},
            {"severity": 3, "message": 'MCP_NODE:{"name":"B","explicit":true,"sorry_deps":[]}'},
            {"severity": 3, "message": 'MCP_SUMMARY:{"visited":10}'},
        ]
        nodes, visited = parse_sorry_result(diags)
        assert len(nodes) == 2
        assert nodes["A"].explicit_sorry is False
        assert nodes["A"].sorry_deps == ["B"]
        assert nodes["B"].explicit_sorry is True
        assert visited == 10

    def test_ignores_non_info(self):
        diags = [{"severity": 1, "message": 'MCP_NODE:{"name":"X","explicit":true,"sorry_deps":[]}'}]
        nodes, _ = parse_sorry_result(diags)
        assert nodes == {}

    def test_empty(self):
        nodes, visited = parse_sorry_result([])
        assert nodes == {}
        assert visited == 0


class TestRenderTree:
    def test_single_explicit(self):
        nodes = {"A": SorryNode("A", explicit_sorry=True, sorry_deps=[])}
        lines = render_tree("A", nodes)
        assert len(lines) == 1
        assert "[explicit sorry]" in lines[0]
        assert "A" in lines[0]

    def test_chain(self):
        nodes = {
            "A": SorryNode("A", explicit_sorry=False, sorry_deps=["B"]),
            "B": SorryNode("B", explicit_sorry=True, sorry_deps=[]),
        }
        lines = render_tree("A", nodes)
        assert len(lines) == 2
        assert "[explicit sorry]" not in lines[0]  # A is transitive
        assert "[explicit sorry]" in lines[1]       # B is explicit

    def test_diamond(self):
        """A depends on B and C, both depend on D (explicit sorry)."""
        nodes = {
            "A": SorryNode("A", explicit_sorry=False, sorry_deps=["B", "C"]),
            "B": SorryNode("B", explicit_sorry=False, sorry_deps=["D"]),
            "C": SorryNode("C", explicit_sorry=False, sorry_deps=["D"]),
            "D": SorryNode("D", explicit_sorry=True, sorry_deps=[]),
        }
        lines = render_tree("A", nodes)
        # D should appear once fully, once as "(see above)"
        full = [l for l in lines if "D" in l and "see above" not in l]
        back = [l for l in lines if "D" in l and "see above" in l]
        assert len(full) == 1
        assert len(back) == 1

    def test_target_not_in_nodes(self):
        """Target not in nodes dict — just prints the name with no tag."""
        lines = render_tree("A", {})
        assert len(lines) == 1
        assert "A" in lines[0]
        assert "[explicit sorry]" not in lines[0]
