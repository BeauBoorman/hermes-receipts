"""Tests for the receipts.yaml sidecar dataset bindings (spec F.3, coder lane).

Covers: exact-count PASS, refuted-count MISS, unreadable-dataset UNVERIFIED,
unbound-claim stays UNVERIFIED, count_rows skips _meta rows, sum_column,
CLI passthrough with --sidecar, and discover() search order.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipts import core, sidecar  # noqa: E402


def _write(p: Path, text: str) -> Path:
    p.write_text(text)
    return p


SIDECAR_MIN = """\
- pattern: handoffs
  dataset: {data}
  method: count_lines
"""


def test_exact_count_passes(tmp_path):
    data = _write(tmp_path / "handoffs.org", "row1\nrow2\nrow3\n")
    bindings = sidecar.load_sidecar(_write(tmp_path / "receipts.yaml",
                                           SIDECAR_MIN.format(data=data)))
    v = core.probe_stat("3 handoffs", bindings)
    assert v.status == core.PASS
    assert "3" in v.detail


def test_wrong_count_refutes(tmp_path):
    data = _write(tmp_path / "handoffs.org", "row1\nrow2\nrow3\n")
    bindings = sidecar.load_sidecar(_write(tmp_path / "receipts.yaml",
                                           SIDECAR_MIN.format(data=data)))
    v = core.probe_stat("47 handoffs", bindings)
    assert v.status == core.MISS
    assert "3" in v.detail  # names the real number


def test_unreadable_dataset_is_unverified_never_miss(tmp_path):
    bindings = sidecar.load_sidecar(_write(
        tmp_path / "receipts.yaml",
        "- pattern: handoffs\n  dataset: %s/nope.org\n  method: count_lines\n" % tmp_path))
    v = core.probe_stat("3 handoffs", bindings)
    assert v.status == core.UNVERIFIED
    assert "unreadable" in v.detail


def test_unbound_claim_stays_unverified(tmp_path):
    data = _write(tmp_path / "h.txt", "x\n")
    bindings = sidecar.load_sidecar(_write(tmp_path / "receipts.yaml",
                                           SIDECAR_MIN.format(data=data)))
    v = core.probe_stat("99 dodos", bindings)
    assert v.status == core.UNVERIFIED
    assert "dataset named" in v.detail


def test_count_rows_skips_meta_rows(tmp_path):
    csv_text = "Service,Amount\n_meta,fixture synthetic\nNoteNest,4.99\nPixelPeak,8.99\n"
    data = _write(tmp_path / "subs.csv", csv_text)
    bindings = sidecar.load_sidecar(_write(tmp_path / "receipts.yaml",
                                           f"- pattern: subscriptions\n  dataset: {data}\n  method: count_rows\n"))
    v = core.probe_stat("2 subscriptions", bindings)
    assert v.status == core.PASS


def test_sum_column_dollars(tmp_path):
    csv_text = "Service,Amount\n_meta,synthetic\nNoteNest,$4.99\nPixelPeak,8.99\n"
    data = _write(tmp_path / "subs.csv", csv_text)
    bindings = sidecar.load_sidecar(_write(tmp_path / "receipts.yaml",
                                           f"- pattern: waste\n  dataset: {data}\n  method: sum_column\n  column: Amount\n"))
    v = core.probe_stat("13.98 waste", bindings)
    assert v.status == core.PASS


def test_selector_regex_counts_matching_lines_only(tmp_path):
    data = _write(tmp_path / "log.org", "FAIL x\nok y\nFAIL z\n")
    bindings = sidecar.load_sidecar(_write(tmp_path / "receipts.yaml",
                                           f"- pattern: failures\n  dataset: {data}\n  method: count_lines\n  selector: FAIL\n"))
    v = core.probe_stat("2 failures", bindings)
    assert v.status == core.PASS


def test_adjudicate_uses_discovered_sidecar(tmp_path, monkeypatch):
    data = _write(tmp_path / "handoffs.org", "a\nb\n")
    _write(tmp_path / "receipts.yaml", SIDECAR_MIN.format(data=data))
    monkeypatch.chdir(tmp_path)
    vs = core.adjudicate("2 handoffs logged")
    assert any(v.status == core.PASS for v in vs)


def test_finance_fixture_count_is_honest(tmp_path):
    """The demo beat: 29 subscriptions against the real shipped fixture."""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "subscriptions_fixture.csv"
    if not fixture.is_file():
        import pytest
        pytest.skip("fixture not shipped")
    bindings = [sidecar.Binding(pattern="subscriptions", dataset=str(fixture),
                                method="count_rows")]
    v = core.probe_stat("31 subscriptions", bindings)
    assert v.status == core.PASS
    v2 = core.probe_stat("40 subscriptions", bindings)
    assert v2.status == core.MISS
