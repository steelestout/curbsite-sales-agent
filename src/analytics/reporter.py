"""
Weekly analytics & cost reporting.

Generates a human-readable report in the terminal and optionally emails it.
"""

import logging
from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table
from tabulate import tabulate

from src.crm.database import get_conn

log = logging.getLogger(__name__)
console = Console()


def _query(sql: str, params: list = None) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params or []).fetchall()
    return [dict(r) for r in rows]


def weekly_report(days: int = 7) -> str:
    """
    Build a weekly report string and print it to the console.
    Returns the report as plain text.
    """
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    lines: list[str] = []

    def h(title: str):
        lines.append(f"\n{'─' * 50}")
        lines.append(f"  {title}")
        lines.append(f"{'─' * 50}")

    lines.append(f"\n{'═' * 50}")
    lines.append(f"  Curbsite Sales Agent — Weekly Report")
    lines.append(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f"{'═' * 50}")

    # ── Lead pipeline ─────────────────────────────────────────────────────────
    h("LEAD PIPELINE")
    pipeline = _query("""
        SELECT status, COUNT(*) as count, ROUND(AVG(score), 1) as avg_score
        FROM leads
        GROUP BY status
        ORDER BY count DESC
    """)
    lines.append(tabulate(pipeline, headers="keys", tablefmt="simple"))

    # ── New leads this period ─────────────────────────────────────────────────
    h(f"NEW LEADS (last {days} days)")
    new_leads = _query("""
        SELECT niche, city, COUNT(*) as count
        FROM leads
        WHERE created_at >= ?
        GROUP BY niche, city
        ORDER BY count DESC
        LIMIT 15
    """, [since])
    lines.append(tabulate(new_leads, headers="keys", tablefmt="simple"))

    # ── Top leads by score ────────────────────────────────────────────────────
    h("TOP 10 LEADS BY SCORE")
    top = _query("""
        SELECT business_name, niche, city, score, status, email
        FROM leads
        ORDER BY score DESC
        LIMIT 10
    """)
    lines.append(tabulate(top, headers="keys", tablefmt="simple"))

    # ── Outreach activity ─────────────────────────────────────────────────────
    h(f"OUTREACH ACTIVITY (last {days} days)")
    outreach = _query("""
        SELECT type, COUNT(*) as sent,
               SUM(opened) as opened,
               SUM(replied) as replied,
               SUM(bounced) as bounced
        FROM outreach_log
        WHERE sent_at >= ?
        GROUP BY type
    """, [since])
    lines.append(tabulate(outreach, headers="keys", tablefmt="simple"))

    # ── Conversion ────────────────────────────────────────────────────────────
    h("CONVERSION FUNNEL")
    funnel = _query("""
        SELECT
            (SELECT COUNT(*) FROM leads) as total_leads,
            (SELECT COUNT(*) FROM leads WHERE status != 'new') as contacted,
            (SELECT COUNT(*) FROM leads WHERE status = 'won') as won,
            (SELECT COUNT(*) FROM leads WHERE status = 'lost') as lost
    """)
    lines.append(tabulate(funnel, headers="keys", tablefmt="simple"))

    # ── AI cost tracking ─────────────────────────────────────────────────────
    h(f"AI COST (last {days} days)")
    costs = _query("""
        SELECT operation, model,
               COUNT(*) as calls,
               SUM(input_tok) as total_in_tok,
               SUM(output_tok) as total_out_tok,
               ROUND(SUM(cost_usd), 4) as total_usd,
               SUM(cached) as cached_hits
        FROM cost_log
        WHERE logged_at >= ?
        GROUP BY operation, model
        ORDER BY total_usd DESC
    """, [since])
    lines.append(tabulate(costs, headers="keys", tablefmt="simple"))

    total_cost = _query("""
        SELECT ROUND(SUM(cost_usd), 4) as total_usd
        FROM cost_log WHERE logged_at >= ?
    """, [since])
    if total_cost:
        lines.append(f"\n  Total AI spend this period: ${total_cost[0]['total_usd'] or 0:.4f}")

    lines.append(f"\n{'═' * 50}\n")

    report = "\n".join(lines)
    console.print(report)
    return report


def cost_summary() -> dict:
    """Return a simple cost summary dict for programmatic use."""
    rows = _query("""
        SELECT ROUND(SUM(cost_usd), 6) as total,
               SUM(CASE WHEN cached=1 THEN 1 ELSE 0 END) as cached_calls,
               COUNT(*) as total_calls
        FROM cost_log
    """)
    return rows[0] if rows else {}
