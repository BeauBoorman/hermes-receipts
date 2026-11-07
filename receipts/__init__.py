"""Hermes plugin entry point for `receipts`.

Registers:
  * transform_llm_output hook — appends a probed RECEIPTS block to every
    outgoing response (works on every platform, no adapter code).
  * receipts_check tool — the model can probe a draft before sending it.
  * /receipts command and `hermes receipts` CLI for on-demand checks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import core

# Receipts are opt-in loud: warning mode only annotates, never blocks, so a
# refusing middleware never gets uninstalled for eating a send.
MAX_CLAIMS = int(os.environ.get("HERMES_RECEIPTS_MAX", "25"))
TIMEOUT = float(os.environ.get("HERMES_RECEIPTS_TIMEOUT", "5"))


def _already_stamped(text: str) -> bool:
    return "**RECEIPTS**" in text


def on_transform_llm_output(response_text: str = "", **kwargs):
    del kwargs
    if not response_text:
        return None
    # A3 self-stamp bypass: a model may hallucinate its own all-✅ RECEIPTS
    # block. Never pass it through — strip it, re-probe the claims, and append
    # a fresh honestly-probed block. Only the plugin's own output renders.
    clean = core.strip_self_stamps(response_text)
    vs = core.adjudicate(clean, timeout=TIMEOUT, limit=MAX_CLAIMS)
    if not vs:
        # no checkable claims — still drop any fabricated stamp
        return clean if clean != response_text else None
    return clean + core.render_block(vs)


def register(ctx):
    ctx.register_hook("transform_llm_output", on_transform_llm_output)

    schema = {
        "name": "receipts_check",
        "description": (
            "Probe every checkable claim in a draft response (filesystem paths, "
            "URLs, 'N of M' stats) and return pass/miss/unverified per claim. "
            "Use before sending a message that cites evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Draft text to check"},
            },
            "required": ["text"],
        },
    }

    def handle(params, **kwargs):
        del kwargs
        vs = core.adjudicate(params.get("text", ""), timeout=TIMEOUT,
                             limit=MAX_CLAIMS)
        return json.dumps({
            "claims": len(vs),
            "failed": sum(1 for v in vs if v.status == core.MISS),
            "receipts": [v.to_dict() for v in vs],
        }, default=str)

    ctx.register_tool(name="receipts_check", toolset="receipts",
                      schema=schema, handler=handle)

    def cmd_receipts(args=""):
        arg = (args or "").strip()
        if not arg:
            return "usage: /receipts <path-to-file>"
        p = Path(os.path.expanduser(arg))
        if not p.exists():
            return f"❌ {arg} — no such file"
        vs = core.adjudicate(p.read_text(), timeout=TIMEOUT, limit=MAX_CLAIMS)
        return core.render_block(vs).lstrip("\n") or "no checkable claims"

    ctx.register_command("receipts", cmd_receipts,
                         "Probe the claims in a text file")
