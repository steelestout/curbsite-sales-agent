"""
Rook sales training module — manages and uploads training data to the
OpenClaw voice agent platform.

What this does
──────────────
1. Loads all training documents from data/rook/
2. Assembles a complete system prompt for Rook
3. Validates the prompt (checks pricing, payment methods, required sections)
4. Uploads to OpenClaw via their API (when OPENCLAW_API_KEY is set)
5. Provides a --dry-run mode to preview the assembled prompt

OpenClaw / Rook Status
──────────────────────
As of this writing, Rook is NOT yet deployed. The agent platform (OpenClaw
or a compatible voice AI provider) is to be configured. This module handles
the data pipeline — the actual agent UI/configuration is separate.

IMPORTANT — FCC compliance for warm calls
─────────────────────────────────────────
Rook may only call leads who have previously engaged (email open, link click,
form fill). Cold AI calling of scraped leads is prohibited under the FCC's
One-to-One Consent Rule (effective Jan 27 2026). See docs/ROOK_SETUP.md.

Run via
───────
  python -m src.rook.sales_training --dry-run        # preview assembled prompt
  python -m src.rook.sales_training --upload          # push to OpenClaw
  python -m src.rook.sales_training --validate        # check prompt completeness
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

from src.outreach.pricing import PRICING, PAYMENT_METHODS, FOUNDING_CLIENTS_REMAINING

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_ROOK_DIR = _ROOT / "data" / "rook"
_SCRIPTS_DIR = _ROOK_DIR / "sales_scripts"

_OPENCLAW_API_KEY: str = os.getenv("OPENCLAW_API_KEY", "")
_OPENCLAW_AGENT_ID: str = os.getenv("OPENCLAW_AGENT_ID", "")
_OPENCLAW_API_BASE: str = os.getenv("OPENCLAW_API_BASE", "https://api.openclaw.ai/v1")


# ── Document loading ──────────────────────────────────────────────────────────

def load_training_prompt() -> str:
    """Load the base training prompt/character brief."""
    prompt_path = _ROOK_DIR / "training_prompt.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Training prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def load_scripts() -> dict[str, str]:
    """Load all sales scripts from data/rook/sales_scripts/."""
    scripts = {}
    if not _SCRIPTS_DIR.exists():
        log.warning("Sales scripts directory not found: %s", _SCRIPTS_DIR)
        return scripts
    for md_file in sorted(_SCRIPTS_DIR.glob("*.md")):
        scripts[md_file.stem] = md_file.read_text(encoding="utf-8")
        log.debug("Loaded script: %s (%d chars)", md_file.stem, len(scripts[md_file.stem]))
    return scripts


def _build_pricing_section() -> str:
    """Generate a compact pricing reference from the live pricing dict."""
    lines = ["## Live Pricing Reference\n"]
    for niche, tiers in PRICING.items():
        if niche in ("default",):
            continue
        lines.append(f"**{niche.title()}**")
        for t in tiers:
            popular = " ← DEFAULT" if t.get("popular") else ""
            lines.append(f"  - {t.get('name','?')} ({t['tier']}): ${t['price']:,} + ${t.get('care',75)}/mo care{popular}")
        lines.append("")
    lines.append(f"\n**Payment methods**: {PAYMENT_METHODS}")
    lines.append(f"\n**Founding client spots remaining**: {FOUNDING_CLIENTS_REMAINING}")
    return "\n".join(lines)


# ── Prompt assembly ───────────────────────────────────────────────────────────

def assemble_system_prompt(include_scripts: bool = True) -> str:
    """
    Assemble the complete system prompt for Rook by combining:
    1. Base character brief (training_prompt.md)
    2. Live pricing data (from pricing.py)
    3. All sales scripts (from data/rook/sales_scripts/)
    """
    sections = []

    # 1. Character brief
    sections.append(load_training_prompt())

    # 2. Live pricing (overrides any pricing in the markdown, ensures it's always current)
    sections.append("---\n\n" + _build_pricing_section())

    # 3. Sales scripts
    if include_scripts:
        scripts = load_scripts()
        for script_name, content in scripts.items():
            sections.append(f"\n---\n\n## Appendix: {script_name.replace('_', ' ').title()}\n\n{content}")

    return "\n\n".join(sections)


# ── Validation ────────────────────────────────────────────────────────────────

_REQUIRED_PHRASES = [
    "mid tier",
    "founding client",
    "free mockup",
    "Stripe",
    "Venmo",
    "CashApp",
    "50%",
    "FCC",
]

_FORBIDDEN_PHRASES = [
    "Zelle",
    "check only",
    "cold call",      # should say "warm call"
    "leverage",
    "synergy",
]


def validate_prompt(prompt: str) -> tuple[bool, list[str]]:
    """
    Check that the assembled prompt contains all required content
    and none of the forbidden phrases.
    Returns (is_valid, list_of_issues).
    """
    issues = []
    prompt_lower = prompt.lower()

    for phrase in _REQUIRED_PHRASES:
        if phrase.lower() not in prompt_lower:
            issues.append(f"MISSING required phrase: '{phrase}'")

    for phrase in _FORBIDDEN_PHRASES:
        if phrase.lower() in prompt_lower:
            issues.append(f"FORBIDDEN phrase found: '{phrase}'")

    is_valid = len(issues) == 0
    return is_valid, issues


# ── OpenClaw upload ───────────────────────────────────────────────────────────

def upload_to_openclaw(prompt: str, agent_id: str = None) -> bool:
    """
    Upload the assembled system prompt to OpenClaw's agent API.

    This is a placeholder implementation — the exact OpenClaw API
    endpoints and payload format may differ. Update the URL and
    payload structure to match OpenClaw's documentation.
    """
    if not _OPENCLAW_API_KEY:
        log.warning(
            "OPENCLAW_API_KEY not set — cannot upload to OpenClaw.\n"
            "Set it in .env and re-run with --upload."
        )
        return False

    target_agent_id = agent_id or _OPENCLAW_AGENT_ID
    if not target_agent_id:
        log.warning("OPENCLAW_AGENT_ID not set — cannot update agent.")
        return False

    headers = {
        "Authorization": f"Bearer {_OPENCLAW_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "system_prompt": prompt,
        "name": "Rook",
        "description": "Curbsite.co sales agent — warm follow-up calls for web design outreach",
    }

    try:
        resp = requests.patch(
            f"{_OPENCLAW_API_BASE}/agents/{target_agent_id}",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        log.info("Rook system prompt uploaded to OpenClaw agent %s", target_agent_id)
        return True
    except requests.RequestException as exc:
        log.error("OpenClaw upload failed: %s", exc)
        if hasattr(exc, "response") and exc.response is not None:
            log.error("Response: %s", exc.response.text[:500])
        return False


def get_rook_call_eligibility(lead: dict) -> tuple[bool, str]:
    """
    Check whether a lead is eligible for a Rook warm-follow-up call.

    Rules (FCC compliance):
    1. Lead must have a phone number
    2. Lead must have prior engagement (email open, link click, or mockup view)
    3. Lead score must be >= 50
    4. Lead must NOT be in 'lost' or 'unsubscribed' status

    Returns (eligible, reason).
    """
    phone = lead.get("phone")
    if not phone:
        return False, "no phone number"

    status = lead.get("status", "")
    if status in ("lost", "unsubscribed"):
        return False, f"lead is {status}"

    score = lead.get("score", 0)
    if score < 50:
        return False, f"score {score} < 50 threshold"

    # Check for prior engagement in the outreach log
    # (The caller should pass a 'has_engagement' flag populated from the outreach log)
    if not lead.get("has_engagement"):
        return False, "no prior email engagement — warm calls require prior engagement for FCC compliance"

    return True, "eligible"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Rook sales training manager")
    parser.add_argument("--dry-run", action="store_true", help="Print assembled prompt, don't upload")
    parser.add_argument("--upload", action="store_true", help="Upload to OpenClaw")
    parser.add_argument("--validate", action="store_true", help="Validate prompt completeness")
    parser.add_argument("--no-scripts", action="store_true", help="Assemble prompt without sales scripts")
    parser.add_argument("--agent-id", type=str, help="Override OPENCLAW_AGENT_ID")
    args = parser.parse_args()

    prompt = assemble_system_prompt(include_scripts=not args.no_scripts)

    if args.validate or args.dry_run:
        is_valid, issues = validate_prompt(prompt)
        if is_valid:
            log.info("✅ Prompt validation passed.")
        else:
            log.warning("⚠️  Prompt validation issues:")
            for issue in issues:
                log.warning("   %s", issue)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("ASSEMBLED ROOK SYSTEM PROMPT")
        print("=" * 60)
        print(f"\nTotal length: {len(prompt):,} characters / ~{len(prompt)//4:,} tokens\n")
        print(prompt[:3000])
        if len(prompt) > 3000:
            print(f"\n... [{len(prompt) - 3000:,} more characters — use --upload to send full prompt] ...")

    if args.upload:
        log.info("Uploading prompt to OpenClaw...")
        success = upload_to_openclaw(prompt, agent_id=args.agent_id)
        if success:
            log.info("✅ Upload complete.")
        else:
            log.error("❌ Upload failed. Check API key and agent ID.")


if __name__ == "__main__":
    main()
