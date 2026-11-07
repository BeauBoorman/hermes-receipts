"""Extraction robustness — research-oracle's lane (HARDENING-SPEC B1–B4).

Invariant under test everywhere below: every plausible claim in the input
yields a Verdict (pass/miss/unverified) or an explicit SKIPPED marker —
silence is a test failure. A trust plugin that quietly ignores a claim
class is worse than one that admits it can't check.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipts import core  # noqa: E402


def statuses(text: str) -> list[tuple[str, str]]:
    return [(v.claim.kind, v.claim.text) for v in core.adjudicate(text)]


def targets(text: str) -> set[str]:
    return {v.claim.target for v in core.adjudicate(text)}


# --- B1: the /var /Volumes /usr silent-skip bug -------------------------

def test_var_log_path_is_not_silently_skipped():
    # v0.1 blanket-skipped any path starting /v or /w — /var/log/system.log
    # and /Volumes/... vanished without a receipt line. Silence is failure.
    before = [c.target for c in core.extract_claims("see /var/log/system.log")]
    if not before:
        import pytest
        pytest.fail("B1 regression: /var/log/system.log extracted to nothing")


def test_var_path_yields_verdict_on_missing():
    vs = core.adjudicate("check /var/log/definitely-not-here.log")
    assert vs, "B1: missing /var path produced no verdict at all"
    assert any("/var/log/definitely-not-horse" in v.claim.target or
               "definitely-not-here" in v.claim.target for v in vs)


def test_volumes_path_extracts():
    got = [c.target for c in core.extract_claims("backup lives on /Volumes/Backup2026/dump.sql")]
    assert any("Volumes" in t for t in got), f"B1: /Volumes path lost: {got}"


def test_version_fragment_still_filtered():
    # the guard exists for api/v2/users fragment matches — keep that behaviour
    got = [c.target for c in core.extract_claims("deployed to api/v2/users endpoint today")]
    assert not any(t.rstrip("/").endswith("/v2") for t in got), got


# --- B2: Windows paths ---------------------------------------------------

def test_windows_path_extracts():
    got = [c.target for c in core.extract_claims("log at C:\\logs\\hermes-agent.log")]
    assert any("logs" in t and "hermes-agent" in t for t in got), f"B2: Windows path lost: {got}"


def test_windows_path_probe_returns_verdict():
    vs = core.adjudicate("log at C:\\logs\\definitely-not-here.log")
    assert vs, "B2: Windows path produced no verdict"
    assert all(v.status in (core.PASS, core.MISS, core.UNVERIFIED) for v in vs)


# --- B3: API-route false-❌ (Research's own repro) ------------------------

def test_api_route_fragment_is_not_miss():
    # Research fed the withdrawn pitch back through and got a false
    # ❌ on `/channels/<id>` — a Discord REST route, probed as a local path.
    vs = core.adjudicate("live GET /channels/1560349780071415861 shows 21 overwrites")
    chan = [v for v in vs if "channels" in v.claim.target]
    if chan:  # extracted at all -> must never be a filesystem MISS
        assert all(v.status != core.MISS for v in chan), \
            f"B3: API route false-❌: {[(v.claim.target, v.status) for v in chan]}"


def test_unanchored_slash_fragment_not_probed_as_path():
    vs = core.adjudicate("I ran hermes plugins install receipts today")
    assert not any("plugins/install" in v.claim.target or
                   v.claim.target.startswith("plugins/") for v in vs), \
        [v.claim.target for v in vs]


# --- B4: fraction / nag regex ---------------------------------------------

def test_version_fraction_not_flagged():
    # B1/gate-A update: the fraction is no longer SILENT — it renders an
    # explicit ⊘ SKIPPED verdict (corpus c06). What must never happen is a
    # spurious ⚠️/❌ on the mangled "3.4/5" sub-span.
    vs = core.adjudicate("upgraded from v2.3.4/5 last week")
    frac = [v for v in vs if v.claim.text == "v2.3.4/5"]
    assert len(frac) == 1 and frac[0].status == core.SKIPPED, \
        f"B4: {[ (v.claim.text, v.status) for v in vs ]}"
    assert not any(v.claim.text == "3.4/5" for v in vs)


def test_section_fraction_not_flagged():
    # same: visible SKIPPED with the exact written span, never a nag verdict
    vs = core.adjudicate("covered in section 3/4 of the guide")
    frac = [v for v in vs if v.claim.kind == "stat" and "3/4" in v.claim.text]
    assert len(frac) == 1 and frac[0].status == core.SKIPPED, \
        f"B4: {[ (v.claim.text, v.status) for v in vs ]}"


def test_legit_x_of_y_still_flagged():
    # the fraction guard must not kill genuine evidence-shaped stats
    vs = core.adjudicate("7 of 10 lanes posted tonight")
    assert any(v.claim.kind == "stat" for v in vs)


# --- B-invariant: extraction exhaustiveness ------------------------------

def test_extraction_exhaustive_no_silence():
    text = (
        "check ~/org/ops/fleet_identity.yaml, /var/log/system.log, "
        "/Volumes/Backup/dump.sql, C:\\logs\\app.log, "
        "https://hermes-agent.nousresearch.com/docs, and 47 handoffs"
    )
    vs = core.adjudicate(text)
    got = {v.claim.target for v in vs}
    for needle in ("fleet_identity.yaml", "/var/log", "Volumes", "docs", "47 handoffs"):
        assert any(needle in t for t in got), \
            f"B-invariant: '{needle}' produced no verdict — silence is a test failure. Got: {sorted(got)}"
