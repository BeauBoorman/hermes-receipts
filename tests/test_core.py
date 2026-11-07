"""Tests for receipts claim extraction and probing. Run: python3 -m pytest -q"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipts import core  # noqa: E402


def test_missing_path_is_miss():
    vs = core.adjudicate("see ~/org/vault/sessions/handoffs.org for the log")
    assert [v.status for v in vs] == [core.MISS]


def test_real_path_is_pass():
    vs = core.adjudicate("see ~/org/ops/fleet_identity.yaml for bindings")
    assert [v.status for v in vs] == [core.PASS]


def test_quoted_path_with_space_survives():
    vs = core.adjudicate("`~/Library/Application Support` holds state")
    assert vs and vs[0].claim.target == "~/Library/Application Support"


def test_code_fence_is_ignored():
    # B1/A-gate update: fenced paths are no longer SILENT — they render an
    # explicit ⊘ SKIPPED marker (spec four-state + corpus case c07). Silence
    # is the failure mode this replaces.
    vs = core.adjudicate("```\n~/nope/does-not-exist\n```\n")
    assert len(vs) == 1
    assert vs[0].status == core.SKIPPED
    assert vs[0].claim.kind == "fenced"


def test_bare_stat_is_unverified_not_pass():
    vs = core.adjudicate("47 handoffs, 6 failed silently")
    assert any(v.status == core.UNVERIFIED for v in vs)
    assert not any(v.status == core.PASS for v in vs)


def test_block_renders_failure_grade():
    vs = core.adjudicate("see ~/nope/missing.md")
    block = core.render_block(vs)
    assert "RECEIPTS" in block
    assert "FAILED probe" in block


def test_unreachable_url_is_unverified_not_miss():
    v = core.probe_url("https://example.invalid/nope", timeout=1.0)
    assert v.status == core.UNVERIFIED
