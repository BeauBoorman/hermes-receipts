"""Core claim extraction + probing for the receipts plugin.

No third-party deps. Every plausible claim yields a Verdict in one of four
states (HARDENING-SPEC A4) or an explicit SKIPPED marker (gate B1: silence
is a test failure):

    PASS        ✅ content-verified   — the cited thing exists AND its content
                                       matched what was claimed (quoted line
                                       re-grepped / dataset counted / path probed)
    LOCATABLE   📍 reachable          — URL resolves or walled (HTTP 401/403/429)
                                       but content was NOT checked. Never a ✅.
    UNVERIFIED  ⚠️ uncheckable        — probe cannot run (remote machine, API
                                       route, walled dataset, blackholed host).
                                       Never a ❌.
    MISS        ❌ refuted            — the claim is FALSE on local evidence:
                                       file missing under a known local root,
                                       dataset count disagrees, HTTP 410/404.

Design rules (hard-won, see HARDENING-SPEC.md):
  * A probe that cannot run is UNVERIFIED, never PASS, never MISS.
  * A URL is never content-verified by reachability alone (Barnaby's
    "54% of users vs 54% of organizations" catch).
  * ❌ only under a known local root (A2): a path absent on the gateway
    host may live on the user's laptop — crying wolf gets uninstalled.
  * Parallel probes under a global wall budget (A1): serial URL probing
    measured 12s/4 and 60s/20 blackholed URLs.
  * Self-stamp bypass (A3): a model hallucinating its own all-✅ RECEIPTS
    block must never survive — re-strip before adjudication.
  * API routes, version fragments, fenced code, prose fractions → SKIPPED
    by class, visibly, not silently.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

from . import sidecar

PASS = "pass"            # ✅ content-verified
LOCATABLE = "locatable"  # 📍 reachable, content unchecked
UNVERIFIED = "unverified"  # ⚠️ cannot check here
MISS = "miss"            # ❌ refuted on local evidence
SKIPPED = "skipped"      # ⊘ not a checkable claim (explicit, gate B1)

# A1: wall-clock budget for one adjudication's probe phase.
WALL_BUDGET_S = float(os.environ.get("HERMES_RECEIPTS_BUDGET", "3.0"))
PROBE_WORKERS = int(os.environ.get("HERMES_RECEIPTS_WORKERS", "8"))
# A4: a ✅ on a URL requires fetching content and re-grepping a claimed
# fragment. Cost-capped: only the first N urls per reply get content checks.
CONTENT_CHECK_MAX = int(os.environ.get("HERMES_RECEIPTS_CONTENT_MAX", "3"))
CONTENT_FETCH_LIMIT = 200_000  # bytes read for a re-grep, keeps cost bounded

# A2: a path missing on THIS host only refutes the claim when it sits under
# a root the probing agent plausibly owns. Anything else degrades to ⚠️ —
# the file may exist on the user's other machine.
OWNED_ROOT_TOKENS = (
    "~/", "~", "./", "../", "/tmp/", "/private/tmp/", "/Users/", "/home/",
)


@dataclass
class Claim:
    kind: str          # path | url | stat | line
    text: str          # as written
    target: str        # what gets probed
    line: int          # line number in the response, for ordering

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    claim: Claim
    status: str        # pass | locatable | unverified | miss | skipped
    detail: str

    def render(self) -> str:
        icon = {PASS: "✅", LOCATABLE: "📍", UNVERIFIED: "⚠️",
                MISS: "❌", SKIPPED: "⊘"}[self.status]
        return f"{icon} `{self.claim.text}` — {self.detail}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claim"] = self.claim.to_dict()
        return d


# ~/foo/bar, /abs/path, ./rel — must look like a path, not prose.
PATH_RE = re.compile(r"(?<![\w/])((?:~|\.{1,2})?/[\w.\-]+(?:/[\w.\-]+)*)")
# Windows paths: C:\logs\x.log, D:\data\file.txt (Hermes runs on Windows).
# `\\+` also matches the doubled-backslash shell-escape variant agents emit
# (C:\\logs\\x.log); segments exclude spaces — unquoted paths with spaces are
# absorbed explicitly at the call site instead, so prose is never swallowed.
WIN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]:\\+[\w\-.]+(?:\\+[\w\-.]+)*)")
# A backtick/quote-wrapped span that starts like a path: keeps "Application Support"
# style segments intact, which the bare regex would truncate at the first space.
QUOTED_PATH_RE = re.compile(r"[`\"']((?:~|\.{1,2})?/[^`\"']+)[`\"']")
URL_RE = re.compile(r"https?://[^\s<>)\]]+")
# 'x of y' / 'x/y' stats. Lookbehind blocks version strings ("v2.3.4/5" must not
# match as "3.4/5"); the separator is captured so slash-fractions ("section 3/4")
# can be told apart from real counts at extraction time.
STAT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(of|/)\s*(\d+)(?!\d)")
# REST/route shapes that look like paths but are not filesystem claims:
# /channels/<id>, /api/v2/..., /users/@me — probing these as paths is a false ❌.
API_ROUTE_HEADS = frozenset(
    {"api", "channels", "guilds", "users", "messages", "webhooks", "invites"})
VERSION_HEAD_RE = re.compile(r"[vw]\d+")
# Evidence-shaped counts ("47 handoffs", "6 failed days") — a bare number next
# to a countable noun reads as a measured claim. Ordinary prose numbers are left
# alone on purpose: a plugin that warns on every "2 fixes" gets muted.
STAT_NOUN_RE = re.compile(
    r"\b(\d{1,5})\s+(hand-?offs?|failures?|fails?|sessions?|days?|messages?|"
    r"incidents?|calls?|requests?|errors?|restarts?|tasks?|profiles?|"
    r"repos?|commits?|tickets?|subscriptions?|rows?|lines?)\b", re.I)
YEAR_RE = re.compile(r"^(19|20)\d\d$")
LINE_RE = re.compile(r"\bL(\d+)(?:[–-]L?(\d+))?\b")
# B4 companion: version-string and section fractions are not evidence counts,
# but per gate B1 they must be visibly SKIPPED with their exact written span,
# not silently dropped.
VERSION_FRACTION_RE = re.compile(r"\b[vw]\d+(?:\.\d+)+/\d+\b")
SECTION_FRACTION_RE = re.compile(
    r"\b(?:sections?|secs?\.?|parts?|steps?|chapters?|pages?|slides?)\s+\d+/\d+\b",
    re.I)
# Absorb a spaced filename into a bare path claim: "~/projects/hermes receipts
# spec.md" — the bare regex stops at the first space, leaving the real claim
# text mangled. A continuation of plain words ending in a filename extension
# (and followed by boundary/EOL) is part of the path, not prose.
SPACED_FILENAME_RE = re.compile(
    r"\s+((?:[\w\-]+\s+)*[A-Za-z0-9][\w\-]*\.[A-Za-z0-9]{1,5})(?=[\s.,;:)]|$)")

RECEIPTS_MARKER = "**RECEIPTS**"


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def strip_self_stamps(text: str) -> str:
    """A3: remove any pre-existing RECEIPTS blocks before adjudication.

    A model can hallucinate its own all-✅ RECEIPTS block; if the plugin
    appended a second one, the fabricated first block would ride along
    looking plugin-authored. Only the plugin's own output may render as a
    receipts block, so every existing block is stripped from the text the
    engine checks — the hook then appends a fresh, honestly-probed one.
    """
    # drop from the marker line back to (and including) the preceding '---'
    out, dropping = [], False
    for raw in text.splitlines():
        if RECEIPTS_MARKER in raw:
            dropping = True
            # remove a trailing '---' separator line we just kept
            if out and out[-1].strip() == "---":
                out.pop()
            continue
        if dropping:
            # block ends at the first line that no longer looks like a
            # rendered verdict (icon + backticked claim) or separator
            if raw.strip() == "" or raw.strip() == "---" or \
                    re.match(r"^[✅📍⚠️❌⊘]", raw.strip()):
                continue
            dropping = False
    # fence state must survive stripping unchanged
        out.append(raw)
    return "\n".join(out)


def extract_claims(text: str) -> list[Claim]:
    """Find checkable claims. Skips fenced code blocks and mid-word matches."""
    claims: list[Claim] = []
    in_fence = False
    fence_spans: list[Claim] = []  # paths inside fences → explicit SKIPPED verdicts
    for i, raw in enumerate(text.splitlines(), start=1):
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            # B1: fenced paths are quoted evidence, not claims — but they must
            # be visibly skipped, not silently dropped.
            for m in PATH_RE.finditer(raw):
                fence_spans.append(Claim("fenced", m.group(1), m.group(1), i))
            continue
        # URLs first; blank them so the path regex does not re-match the host.
        # Trailing sentence punctuation (.,;:!?) is stripped — an unstripped
        # trailing dot turns a real link into "HTTP 404" and refutes a TRUE
        # claim (caught live in the A4 demo: ".../kanban." vs ".../kanban").
        scrubbed = raw
        for m in URL_RE.finditer(raw):
            url_text = m.group(0).rstrip(".,;:!?")
            claims.append(Claim("url", url_text, url_text, i))
        scrubbed = URL_RE.sub(" ", scrubbed)

        # quoted paths before bare ones, then mask so they are not re-matched
        for m in QUOTED_PATH_RE.finditer(scrubbed):
            cand = m.group(1).strip().rstrip(".,;:")
            claims.append(Claim("path", cand, cand, i))
        scrubbed = QUOTED_PATH_RE.sub(" ", scrubbed)

        # Windows paths (B2): Hermes runs on Windows too. Extract, then mask.
        for m in WIN_PATH_RE.finditer(scrubbed):
            claims.append(Claim("path", m.group(1), m.group(1), i))
        scrubbed = WIN_PATH_RE.sub(" ", scrubbed)

        for m in PATH_RE.finditer(scrubbed):
            cand = m.group(1).rstrip(".,;:)")
            # a lone "/" or a date fragment is not a claim
            if cand.count("/") < 1 or len(cand) < 4:
                continue
            if VERSION_HEAD_RE.match(cand.lstrip("/")):
                continue  # /v2/ or /w3/ version fragment, not a path
            # unquoted spaced filename: "~/projects/hermes receipts spec.md"
            rest = scrubbed[m.end():]
            absorb = SPACED_FILENAME_RE.match(rest)
            if absorb and "." in absorb.group(1):
                cand = cand + " " + absorb.group(1)
            claims.append(Claim("path", cand, cand, i))

        # B4 + B1: version/section fractions are skipped claims — visible
        # SKIPPED verdicts carrying their exact written span, never silence.
        for rx in (VERSION_FRACTION_RE, SECTION_FRACTION_RE):
            for m in rx.finditer(scrubbed):
                claims.append(Claim("stat", m.group(0), m.group(0), i, ))

        for m in STAT_RE.finditer(scrubbed):
            num, sep, den = m.group(1), m.group(2), m.group(3)
            # B4: slash-fractions are almost never evidence counts. Accept
            # "3/4" only when the numerator is a plausible ordinal position
            # of a real count — i.e. x <= y and NOT both single digits
            # (sections, quiz scores, screen ratios). "7 of 10", "12/25" pass.
            if sep == "/" and float(num) <= float(den) and len(num) == 1 and len(den) == 1:
                continue
            claims.append(Claim("stat", m.group(0), m.group(0), i))

        for m in STAT_NOUN_RE.finditer(scrubbed):
            if YEAR_RE.match(m.group(1)):
                continue
            claims.append(Claim("stat", m.group(0), m.group(0), i))
    # B1: fenced-quoted paths become explicit fenced claims → visible
    # SKIPPED verdicts (quoted evidence, not the sender's claim) — never silent.
    claims.extend(fence_spans)
    return claims


def _is_api_route(p: str) -> bool:
    """B3: REST-route shapes are not filesystem claims.

    '/channels/<snowflake>', '/api/v2/...', '/users/@me' — probing these as
    paths stamps a false ❌ on a correct claim (Research's live repro).
    """
    parts = [s for s in p.split("/") if s]
    if not parts:
        return False
    head = parts[0].lower()
    if head in API_ROUTE_HEADS:
        return True
    # /<service>/v2/... versioned route shapes
    if len(parts) >= 2 and VERSION_HEAD_RE.fullmatch(parts[1]) and head not in ("opt", "usr", "var", "Volumes"):
        return True
    # all-snowflake segments: /channels/1560.../messages/1560...
    digits = [s for s in parts if s.isdigit()]
    return len(parts) >= 2 and len(digits) >= 2 and len(digits) == len(parts) - 1


def _owned_root(p: str) -> bool:
    """A2: is this path anchored somewhere the probing host plausibly owns?

    '~/' and relative paths are the agent's own workspace — a miss there is
    a real miss. '/var', '/etc', '/usr', 'C:\\' are other machines' roots
    (servers, Windows hosts) — absent here says nothing, so ⚠️ never ❌.
    """
    if p.startswith(("~", "./", "../")) or not p.startswith("/"):
        return True
    return p.startswith(("/tmp/", "/private/tmp/", "/Users/", "/home/"))


def probe_path(p: str) -> Verdict:
    claim = Claim("path", p, p, 0)
    if _is_api_route(p):
        return Verdict(claim, SKIPPED, "API route fragment — not a filesystem claim")
    if re.match(r"^[A-Za-z]:\\", p):
        # Windows path: only checkable when we're ON Windows (or can see it
        # through WSL); otherwise it's another machine's filesystem.
        if os.name != "nt" and shutil.which("wslpath") is None:
            return Verdict(claim, UNVERIFIED,
                           "Windows path on a POSIX probe host — not checkable here")
    path = _expand(p)
    # A2 guard must run BEFORE exists(): a foreign-root path that happens to
    # exist on the probe host (e.g. /etc/hosts) must never stamp ✅ — the
    # disclosure promises foreign roots are never probed (DA Gate B1).
    if not _owned_root(p):
        return Verdict(claim, UNVERIFIED,
                       "foreign root — not probed, may exist on another machine")
    if path.exists():
        try:
            size = path.stat().st_size
        except OSError as e:
            return Verdict(claim, UNVERIFIED, f"stat failed: {e.__class__.__name__}")
        kind = "dir" if path.is_dir() else f"{size}B"
        return Verdict(claim, PASS, f"exists ({kind})")
    return Verdict(claim, MISS, "no such file or directory")


def probe_url(url: str, timeout: float = 5.0,
              content_hint: str | None = None) -> Verdict:
    """A4: reachability is 📍 LOCATABLE, never ✅, unless content re-greps.

    content_hint: a short fragment the claim asserts appears at this URL
    (e.g. a quoted line). If provided and found verbatim in the first
    CONTENT_FETCH_LIMIT bytes, the verdict upgrades to ✅ PASS
    content-verified. Anything else stays 📍 — Barnaby's "54% of users" vs
    "54% of organizations" case must never stamp green on a bare 200.
    """
    claim = Claim("url", url, url, 0)
    req = urllib.request.Request(url, method="HEAD",
                                headers={"User-Agent": "hermes-receipts/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        # 401/403/429 means it exists but is walled — located, not verified
        if e.code in (401, 403, 405, 429):
            return Verdict(claim, LOCATABLE, "reachable, walled")
        return Verdict(claim, MISS, f"HTTP {e.code}")
    except (urllib.error.URLError, socket.timeout) as e:
        return Verdict(claim, UNVERIFIED, f"unreachable: {e.__class__.__name__}")

    if status >= 400:
        return Verdict(claim, MISS, f"HTTP {status}")
    if content_hint:
        try:
            get_req = urllib.request.Request(
                url, headers={"User-Agent": "hermes-receipts/0.2"})
            with urllib.request.urlopen(get_req, timeout=timeout) as r:
                body = r.read(CONTENT_FETCH_LIMIT).decode("utf-8", "replace")
            if content_hint.strip() and content_hint.strip() in body:
                return Verdict(claim, PASS, f"content-verified (quote found, HTTP {status})")
            return Verdict(claim, LOCATABLE,
                           f"HTTP {status} — quote not found on page; located, not verified")
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            return Verdict(claim, LOCATABLE,
                           f"HTTP {status} but content fetch failed ({e.__class__.__name__})")
    return Verdict(claim, LOCATABLE, f"HTTP {status} — located, content not checked")


def probe_stat(text: str, bindings: list[sidecar.Binding] | None = None) -> Verdict:
    """A bare 'x of y' is unresolvable without context — say so, do not pass it.

    If a sidecar `receipts.yaml` binds the claim's noun to a dataset, count
    against it: exact → PASS, mismatch → MISS (refuted), dataset unreadable →
    UNVERIFIED (a binding that cannot run is not evidence of fabrication).
    """
    claim = Claim("stat", text, text, 0)
    # B4 + B1: version/section fractions are skipped-by-class, visibly.
    if VERSION_FRACTION_RE.fullmatch(text.strip()) or \
            SECTION_FRACTION_RE.fullmatch(text.strip()):
        return Verdict(claim, SKIPPED,
                       "version/fraction string — not an evidence count")
    b = sidecar.match(text, bindings or [])
    if b is None:
        return Verdict(claim, UNVERIFIED,
                       "arithmetic claim — needs its dataset named to be checkable")
    got = sidecar.evaluate(b)
    if got is None:
        return Verdict(claim, UNVERIFIED,
                       f"dataset unreadable: {b.dataset}")
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m and abs(float(m.group(1)) - got) < 0.005:
        return Verdict(claim, PASS, f"{int(got) if got == int(got) else got} counted in {Path(b.dataset).name}")
    return Verdict(claim, MISS,
                   f"refuted: dataset says {int(got) if got == int(got) else got}, claim says {m.group(1) if m else '?'}")


def probe(claim: Claim, timeout: float = 5.0,
          bindings: list[sidecar.Binding] | None = None) -> Verdict:
    if claim.kind == "fenced":
        return Verdict(claim, SKIPPED,
                       "quoted inside a code fence — evidence, not a claim")
    if claim.kind == "path":
        return probe_path(claim.target)
    if claim.kind == "url":
        return probe_url(claim.target, timeout)
    return probe_stat(claim.target, bindings)


def adjudicate(text: str, timeout: float = 5.0, limit: int = 25,
               bindings: list[sidecar.Binding] | None = None) -> list[Verdict]:
    """Probe claims in parallel under a global wall budget (A1).

    Fanned out with ThreadPoolExecutor (probes are I/O-bound); the budget
    caps total wall time so a reply can never wait on stragglers — workers
    that miss the deadline are cancelled and their claims degrade to ⚠️.
    """
    import time
    if bindings is None:
        bindings = sidecar.discover()
    text = strip_self_stamps(text)  # A3
    seen: set[tuple[str, str]] = set()
    claims: list[Claim] = []
    for c in extract_claims(text):
        key = (c.kind, c.target)
        if key in seen:
            continue
        seen.add(key)
        claims.append(c)
        if len(claims) >= limit:
            break

    # cheap local verdicts first (skips, stats, path classes)
    def _local(c: Claim) -> Verdict | None:
        if c.kind == "fenced":
            return probe(c)  # SKIPPED, no I/O
        if c.kind == "path" and (_is_api_route(c.target) or
                                 re.match(r"^[A-Za-z]:\\", c.target)):
            return probe_path(c.target)          # class verdict, no I/O
        if c.kind == "stat":
            return probe_stat(c.target, bindings)  # local dataset I/O only
        return None

    verdicts: list[Verdict] = []
    pending: list[Claim] = []
    for c in claims:
        v = _local(c)
        if v is not None:
            verdicts.append(v)
        else:
            pending.append(c)

    deadline = time.monotonic() + WALL_BUDGET_S
    if pending:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(PROBE_WORKERS, len(pending))) as ex:
            futs = {ex.submit(probe, c, timeout, bindings): c for c in pending}
            for fut in concurrent.futures.as_completed(futs):
                c = futs[fut]
                if time.monotonic() > deadline:
                    fut.cancel()
                    verdicts.append(Verdict(
                        c, UNVERIFIED, "probe exceeded wall budget — unchecked"))
                    continue
                try:
                    verdicts.append(fut.result(timeout=max(
                        0.1, deadline - time.monotonic())))
                except concurrent.futures.TimeoutError:
                    verdicts.append(Verdict(
                        c, UNVERIFIED, "probe exceeded wall budget — unchecked"))
                except Exception as e:  # a crashing probe is ⚠️, never a crash
                    verdicts.append(Verdict(
                        c, UNVERIFIED, f"probe error: {e.__class__.__name__}"))

    verdicts.sort(key=lambda v: v.claim.line)
    return verdicts


def render_block(verdicts: list[Verdict]) -> str:
    if not verdicts:
        return ""
    counts = {PASS: 0, LOCATABLE: 0, MISS: 0, UNVERIFIED: 0, SKIPPED: 0}
    for v in verdicts:
        counts[v.status] = counts.get(v.status, 0) + 1
    if counts[MISS]:
        grade = f"{counts[MISS]} claim(s) FAILED probe"
    elif counts[UNVERIFIED]:
        grade = "no failures, some claims unverifiable"
    else:
        grade = "all claims verified"
    lines = ["", "---", f"**RECEIPTS** — {len(verdicts)} claim(s) checked · {grade}"]
    for v in verdicts:
        lines.append(v.render())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="hermes receipts",
                                 description="Probe the claims in a text file or post.")
    ap.add_argument("path", help="file to check ('-' reads stdin)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--timeout", type=float, default=5.0)
    a = ap.parse_args(argv)
    text = (Path(a.path).read_text() if a.path != "-"
            else __import__("sys").stdin.read())
    vs = adjudicate(text, a.timeout)
    if a.json:
        print(json.dumps([v.to_dict() for v in vs], indent=2))
    else:
        print(render_block(vs).lstrip("\n"))
    return 1 if any(v.status == MISS for v in vs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
