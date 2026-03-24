"""Integration tests for lean_profile_proof tool.

These tests run actual Lean profiling and verify the output structure.
If Lean's profiler format changes, these tests should fail.
"""

import asyncio
import os
import signal
from pathlib import Path

import pytest

from lean_lsp_mcp.profile_utils import _run_lean_profile, profile_theorem
from tests.helpers.mcp_client import MCPToolError, result_json


class TestProfileTheorem:
    """Direct API tests - run real Lean profiling."""

    @pytest.fixture
    def profile_file(self, test_project_path: Path) -> Path:
        return test_project_path / "ProfileTest.lean"

    @pytest.mark.asyncio
    async def test_profiles_rw_theorem(self, profile_file: Path):
        """Line 3: theorem simple_by using rw tactic."""
        profile = await profile_theorem(
            profile_file, theorem_line=3, project_path=profile_file.parent
        )
        assert profile.ms > 0
        assert len(profile.categories) > 0
        # Should extract timing for line 4 (rw)
        if profile.lines:
            ln = profile.lines[0]
            assert ln.line == 4  # rw is on line 4
            assert "rw" in ln.text

    @pytest.mark.asyncio
    async def test_profiles_simp_theorem(self, profile_file: Path):
        """Line 6: theorem simp_test using simp tactic."""
        profile = await profile_theorem(
            profile_file, theorem_line=6, project_path=profile_file.parent
        )
        assert profile.ms > 0
        assert "simp" in profile.categories
        if profile.lines:
            assert "simp" in profile.lines[0].text

    @pytest.mark.asyncio
    async def test_profiles_omega_theorem(self, profile_file: Path):
        """Line 9: theorem omega_test using omega tactic."""
        profile = await profile_theorem(
            profile_file, theorem_line=9, project_path=profile_file.parent
        )
        assert profile.ms > 0
        if profile.lines:
            ln = profile.lines[0]
            assert ln.line == 10  # omega is on line 10
            assert "omega" in ln.text
            assert ln.ms > 0

    @pytest.mark.asyncio
    async def test_invalid_line_raises(self, profile_file: Path):
        with pytest.raises(ValueError):
            await profile_theorem(
                profile_file, theorem_line=999, project_path=profile_file.parent
            )


class TestProfileProofTool:
    """MCP tool tests."""

    @pytest.mark.asyncio
    async def test_returns_structured_profile(
        self, mcp_client_factory, test_project_path: Path
    ):
        async with mcp_client_factory() as client:
            result = await client.call_tool(
                "lean_profile_proof",
                {
                    "file_path": str(test_project_path / "ProfileTest.lean"),
                    "line": 6,
                },
            )
            data = result_json(result)
            assert data["ms"] > 0
            assert "simp" in data["categories"]
            # Verify line structure
            if data["lines"]:
                ln = data["lines"][0]
                assert "text" in ln and "ms" in ln and "line" in ln

    @pytest.mark.asyncio
    async def test_error_on_invalid_line(
        self, mcp_client_factory, test_project_path: Path
    ):
        async with mcp_client_factory() as client:
            with pytest.raises(MCPToolError):
                await client.call_tool(
                    "lean_profile_proof",
                    {
                        "file_path": str(test_project_path / "ProfileTest.lean"),
                        "line": 999,
                    },
                )


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup is POSIX-specific")
async def test_profile_timeout_kills_process_group(monkeypatch, tmp_path: Path):
    class FakeProc:
        def __init__(self):
            self.pid = 424242
            self.kill_called = False
            self.wait_called = False

        async def communicate(self):
            return b"", b""

        def kill(self):
            self.kill_called = True

        async def wait(self):
            self.wait_called = True
            return 0

    proc = FakeProc()
    seen_kwargs = {}
    killpg_calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_kwargs.update(kwargs)
        return proc

    async def fake_wait_for(awaitable, timeout):
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        raise asyncio.TimeoutError

    def fake_killpg(pid, sig):
        killpg_calls.append((pid, sig))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(os, "killpg", fake_killpg)

    with pytest.raises(TimeoutError, match="Profiling timed out"):
        await _run_lean_profile(tmp_path / "Tmp.lean", tmp_path, timeout=0.01)

    assert seen_kwargs["start_new_session"] is True
    assert killpg_calls == [(proc.pid, signal.SIGKILL)]
    assert proc.wait_called is True
    assert proc.kill_called is False
