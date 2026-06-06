"""
Curbsite Owner Analytics Dashboard — standalone Flask app.

Serves:
  GET  /                       → Dashboard UI (tabbed, mobile-first)
  GET  /preview/<id>/          → Serve built site files for Steele preview
  GET  /preview/<id>/<path>    → Static assets for preview
  GET  /approve/<token>        → Approve build, send client review email
  GET  /reject/<token>         → Reject build, flag revision needed
  GET  /api/stats              → JSON snapshot for external consumers

Deploy on Hostinger VPS alongside the CRM:
  gunicorn -w 2 -b 0.0.0.0:5050 'src.dashboard.app:app'

Nginx proxy (add to curbsite.co site config):
  location /analytics/ {
      proxy_pass http://127.0.0.1:5050/;
  }
"""

import json
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, send_from_directory, url_for

from src.config import DASHBOARD_URL, DB_PATH, PORTAL_URL
from src.crm.database import get_conn
from src.notifications.client_status import approve_build, reject_build

log = logging.getLogger(__name__)
app = Flask(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILD_DIR = _ROOT / "data" / "builds"

# ── Data helpers ──────────────────────────────────────────────────────────────

def _q(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _q1(sql: str, params: tuple = ()) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _stats() -> dict:
    # ── Pipeline ──────────────────────────────────────────────────────────────
    stage_order = [
        "new", "scored", "mockup_ready", "emailed", "followed_up", "mockup_sent",
        "agreed_pending", "agreed", "building", "build_ready", "domain_purchased",
        "vps_provisioned", "deployed", "live",
    ]
    pipeline_raw = _q("SELECT status, COUNT(*) as cnt FROM leads GROUP BY status")
    pipeline = {r["status"]: r["cnt"] for r in pipeline_raw}
    pipeline_ordered = [(s, pipeline.get(s, 0)) for s in stage_order]
    lost = pipeline.get("lost", 0) + pipeline.get("unsubscribed", 0)

    # ── Revenue ───────────────────────────────────────────────────────────────
    # Estimate: billed = agreed leads * tier price; collected = deployed+live * tier price
    tier_prices = {"entry": 800, "mid": 1500, "top": 2600}
    revenue_rows = _q(
        "SELECT tier, care_plan, status FROM leads WHERE status NOT IN ('new','scored','lost','unsubscribed')"
    )
    billed = collected = care_mrr = 0
    for r in revenue_rows:
        price = tier_prices.get(r["tier"] or "entry", 800)
        billed += price
        if r["status"] in ("deployed", "live", "delivered"):
            collected += price
        if r["care_plan"] and r["status"] == "live":
            care_mrr += float(r["care_plan"])

    outstanding = billed - collected
    projected_mrr = care_mrr  # recurring from live care-plan clients

    # ── Close rate ────────────────────────────────────────────────────────────
    emailed_count = sum(pipeline.get(s, 0) for s in (
        "emailed", "followed_up", "mockup_sent", "agreed_pending", "agreed",
        "building", "build_ready", "domain_purchased", "vps_provisioned",
        "deployed", "live", "lost",
    ))
    closed_count = sum(pipeline.get(s, 0) for s in (
        "agreed", "building", "build_ready", "domain_purchased",
        "vps_provisioned", "deployed", "live",
    ))
    close_rate = round(closed_count / emailed_count * 100, 1) if emailed_count else 0.0

    # ── Outreach ──────────────────────────────────────────────────────────────
    outreach = _q1(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN opened=1 THEN 1 ELSE 0 END) as opened, "
        "SUM(CASE WHEN replied=1 THEN 1 ELSE 0 END) as replied "
        "FROM outreach_log WHERE type='email'"
    ) or {"total": 0, "opened": 0, "replied": 0}

    # ── AI costs ──────────────────────────────────────────────────────────────
    cost_rows = _q("SELECT operation, SUM(cost_usd) as total FROM cost_log GROUP BY operation")
    total_ai_cost = sum(r["total"] for r in cost_rows)
    cost_breakdown = {r["operation"]: round(r["total"], 4) for r in cost_rows}

    # ── VPS costs ─────────────────────────────────────────────────────────────
    vps_rows = _q("SELECT SUM(monthly_cost) as total, COUNT(*) as count FROM vps_instances")
    vps_monthly = (vps_rows[0]["total"] or 0) if vps_rows else 0
    vps_count = (vps_rows[0]["count"] or 0) if vps_rows else 0

    # ── Clients table ─────────────────────────────────────────────────────────
    clients = _q(
        "SELECT l.id, l.business_name, l.owner_name, l.niche, l.tier, l.status, "
        "l.care_plan, l.domain, v.monthly_cost as vps_cost "
        "FROM leads l LEFT JOIN vps_instances v ON v.lead_id=l.id "
        "WHERE l.status NOT IN ('new','scored','lost','unsubscribed','mockup_ready') "
        "ORDER BY l.updated_at DESC"
    )

    # ── Rook / calls ──────────────────────────────────────────────────────────
    rook = _q(
        "SELECT ol.lead_id, ol.sent_at, ol.error, l.business_name, l.phone "
        "FROM outreach_log ol JOIN leads l ON l.id=ol.lead_id "
        "WHERE ol.type='call' ORDER BY ol.sent_at DESC LIMIT 50"
    )
    calls_total = _q1("SELECT COUNT(*) as n FROM outreach_log WHERE type='call'") or {"n": 0}
    calls_attempted = calls_total["n"]

    # ── Portfolio ─────────────────────────────────────────────────────────────
    portfolio = _q(
        "SELECT m.lead_id, m.netlify_url, l.business_name, l.niche, l.domain "
        "FROM mockups m JOIN leads l ON l.id=m.lead_id "
        "WHERE m.netlify_url IS NOT NULL ORDER BY m.created_at DESC LIMIT 20"
    )

    # ── Price optimiser ───────────────────────────────────────────────────────
    total_live = pipeline.get("live", 0)
    target_clients = 40
    clients_to_threshold = max(0, target_clients - total_live)
    target_close_rate = 27.5  # midpoint of 25-30%

    # ── Pending approvals ─────────────────────────────────────────────────────
    pending_approvals = _q(
        "SELECT l.id, l.business_name, l.niche, l.updated_at "
        "FROM leads l WHERE l.status='build_ready' AND l.build_approved=0 AND l.revision_needed=0 "
        "ORDER BY l.updated_at DESC"
    )
    revision_needed = _q(
        "SELECT id, business_name, niche FROM leads WHERE revision_needed=1 ORDER BY updated_at DESC"
    )

    return {
        "pipeline_ordered": pipeline_ordered,
        "pipeline": pipeline,
        "lost": lost,
        "revenue": {
            "billed": billed,
            "collected": collected,
            "outstanding": outstanding,
            "care_mrr": round(care_mrr, 2),
            "projected_mrr": round(projected_mrr, 2),
        },
        "close_rate": close_rate,
        "closed_count": closed_count,
        "emailed_count": emailed_count,
        "outreach": outreach,
        "ai_cost": round(total_ai_cost, 4),
        "cost_breakdown": cost_breakdown,
        "vps_monthly": round(vps_monthly, 2),
        "vps_count": vps_count,
        "clients": clients,
        "rook": rook,
        "calls_attempted": calls_attempted,
        "portfolio": portfolio,
        "total_live": total_live,
        "clients_to_threshold": clients_to_threshold,
        "target_close_rate": target_close_rate,
        "pending_approvals": pending_approvals,
        "revision_needed": revision_needed,
    }


# ── HTML template ─────────────────────────────────────────────────────────────

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Curbsite — Owner Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0d1a0d;--card:#162616;--card2:#1a2e1a;--accent:#5cb85c;
  --accent2:#81c784;--text:#e8f5e9;--muted:#8fbc8f;--border:#1e3a1e;
  --red:#ef5350;--amber:#ffa726;--white:#fff;--radius:10px;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',Arial,sans-serif;
     font-size:15px;min-width:375px;}

/* ── Top bar ── */
.topbar{background:var(--card2);border-bottom:1px solid var(--border);
        padding:14px 20px;display:flex;align-items:center;gap:14px;
        position:sticky;top:0;z-index:100;}
.topbar h1{font-size:18px;font-weight:700;letter-spacing:1px;color:var(--accent);}
.topbar .refresh-info{font-size:12px;color:var(--muted);margin-left:auto;}
.topbar .badge{background:var(--accent);color:#000;border-radius:99px;
               font-size:11px;font-weight:700;padding:2px 8px;}

/* ── Tab nav ── */
.tabs{background:var(--card);border-bottom:1px solid var(--border);
      overflow-x:auto;white-space:nowrap;-webkit-overflow-scrolling:touch;
      scrollbar-width:none;}
.tabs::-webkit-scrollbar{display:none;}
.tab-btn{display:inline-block;padding:13px 18px;font-size:13px;font-weight:600;
         color:var(--muted);cursor:pointer;border:none;background:none;
         border-bottom:3px solid transparent;transition:all .15s;}
.tab-btn.active,.tab-btn:hover{color:var(--text);border-bottom-color:var(--accent);}

/* ── Main layout ── */
main{padding:16px;}
.section{display:none;}
.section.active{display:block;}

/* ── Stat cards ── */
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px;}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
           padding:18px 16px;}
.stat-card .label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px;}
.stat-card .value{font-size:28px;font-weight:700;color:var(--white);}
.stat-card .sub{font-size:12px;color:var(--muted);margin-top:4px;}
.stat-card.green .value{color:var(--accent);}
.stat-card.amber .value{color:var(--amber);}
.stat-card.red .value{color:var(--red);}

/* ── Chart containers ── */
.chart-wrap{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
            padding:16px;margin-bottom:16px;}
.chart-wrap h3{font-size:14px;color:var(--muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:.6px;}
.chart-wrap canvas{max-height:280px;}

/* ── Tables ── */
.tbl-wrap{overflow-x:auto;border-radius:var(--radius);border:1px solid var(--border);margin-bottom:16px;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{background:var(--card2);color:var(--muted);font-size:11px;text-transform:uppercase;
   letter-spacing:.5px;padding:10px 14px;text-align:left;white-space:nowrap;}
td{padding:10px 14px;border-top:1px solid var(--border);color:var(--text);}
tr:hover td{background:#1f3a1f;}

/* ── Funnel bars ── */
.funnel{margin-bottom:16px;}
.funnel-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
.funnel-label{min-width:140px;font-size:12px;color:var(--muted);text-align:right;}
.funnel-bar-wrap{flex:1;background:var(--card2);border-radius:4px;height:22px;position:relative;}
.funnel-bar{height:100%;background:var(--accent);border-radius:4px;transition:width .3s;}
.funnel-count{min-width:32px;font-size:13px;font-weight:600;color:var(--white);}

/* ── Portfolio grid ── */
.portfolio-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:16px;}
.portfolio-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
                overflow:hidden;text-decoration:none;color:var(--text);transition:border-color .15s;}
.portfolio-card:hover{border-color:var(--accent);}
.portfolio-thumb{width:100%;height:130px;object-fit:cover;background:var(--card2);}
.portfolio-thumb-placeholder{width:100%;height:130px;background:var(--card2);display:flex;
                              align-items:center;justify-content:center;font-size:30px;}
.portfolio-meta{padding:10px 12px;}
.portfolio-meta strong{display:block;font-size:13px;margin-bottom:2px;}
.portfolio-meta span{font-size:11px;color:var(--muted);}

/* ── Approval alerts ── */
.alert{border-radius:var(--radius);padding:14px 18px;margin-bottom:12px;font-size:14px;}
.alert.warn{background:#3a2a00;border:1px solid #6a4a00;color:#ffcc80;}
.alert.success{background:#003a10;border:1px solid #005a18;color:#a5d6a7;}
.alert.danger{background:#3a0000;border:1px solid #6a0000;color:#ef9a9a;}
.alert strong{display:block;margin-bottom:4px;}

/* ── Price gauge ── */
.gauge-wrap{text-align:center;padding:20px;}
.gauge-value{font-size:48px;font-weight:700;color:var(--accent);}
.gauge-label{font-size:14px;color:var(--muted);margin-top:6px;}
.gauge-sub{font-size:13px;color:var(--text);margin-top:10px;line-height:1.6;}
.progress-bar{background:var(--card2);border-radius:4px;height:12px;margin:12px 0;overflow:hidden;}
.progress-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .4s;}

/* ── Responsive: tablet+ ── */
@media(min-width:600px){
  .card-grid{grid-template-columns:repeat(3,1fr);}
  main{padding:20px;}
}
@media(min-width:900px){
  .card-grid{grid-template-columns:repeat(4,1fr);}
  main{padding:24px;}
  .tab-btn{padding:14px 22px;font-size:14px;}
}
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
  <h1>CURBSITE</h1>
  <span class="badge">Owner</span>
  {% if stats.pending_approvals %}
  <span class="badge" style="background:var(--amber);">{{ stats.pending_approvals|length }} needs approval</span>
  {% endif %}
  <span class="refresh-info">Auto-refreshes every 5 min &bull; Last: <span id="last-refresh">now</span></span>
</div>

<!-- Tabs -->
<nav class="tabs" role="tablist">
  <button class="tab-btn active" onclick="showTab('pipeline')">Pipeline</button>
  <button class="tab-btn" onclick="showTab('revenue')">Revenue</button>
  <button class="tab-btn" onclick="showTab('closerate')">Close Rate</button>
  <button class="tab-btn" onclick="showTab('clients')">Clients</button>
  <button class="tab-btn" onclick="showTab('costs')">Costs</button>
  <button class="tab-btn" onclick="showTab('rook')">Rook</button>
  <button class="tab-btn" onclick="showTab('portfolio')">Portfolio</button>
  <button class="tab-btn" onclick="showTab('optimizer')">Price Optimizer</button>
</nav>

<main>

<!-- ── PIPELINE ─────────────────────────────────────────────────────── -->
<section id="tab-pipeline" class="section active">
  {% if stats.pending_approvals %}
  <div class="alert warn">
    <strong>⚠ Builds awaiting your approval ({{ stats.pending_approvals|length }})</strong>
    {% for a in stats.pending_approvals %}
    <div style="margin-top:6px;">
      <strong>{{ a.business_name }}</strong> ({{ a.niche }}) &mdash;
      <a href="{{ dashboard_url }}/preview/{{ a.id }}/" style="color:#ffcc80;">Preview</a>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if stats.revision_needed %}
  <div class="alert danger">
    <strong>✗ Revision needed ({{ stats.revision_needed|length }})</strong>
    {% for r in stats.revision_needed %}
    <div style="margin-top:4px;">{{ r.business_name }} — Lead #{{ r.id }}</div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="card-grid">
    <div class="stat-card green">
      <div class="label">Live Sites</div>
      <div class="value">{{ stats.total_live }}</div>
      <div class="sub">active clients</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Leads</div>
      <div class="value">{{ stats.pipeline.values()|sum }}</div>
      <div class="sub">in CRM</div>
    </div>
    <div class="stat-card amber">
      <div class="label">In Pipeline</div>
      <div class="value">{{ stats.emailed_count }}</div>
      <div class="sub">emailed or later</div>
    </div>
    <div class="stat-card red">
      <div class="label">Lost</div>
      <div class="value">{{ stats.lost }}</div>
      <div class="sub">lost / unsubscribed</div>
    </div>
  </div>

  <div class="chart-wrap">
    <h3>Pipeline Funnel</h3>
    <div class="funnel" id="funnel-bars">
      {% set max_count = stats.pipeline_ordered | map(attribute=1) | max %}
      {% for stage, count in stats.pipeline_ordered %}
      <div class="funnel-row">
        <div class="funnel-label">{{ stage.replace('_',' ') }}</div>
        <div class="funnel-bar-wrap">
          <div class="funnel-bar" style="width:{{ (count / [max_count,1]|max * 100)|int }}%"></div>
        </div>
        <div class="funnel-count">{{ count }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
</section>

<!-- ── REVENUE ──────────────────────────────────────────────────────── -->
<section id="tab-revenue" class="section">
  <div class="card-grid">
    <div class="stat-card">
      <div class="label">Total Billed</div>
      <div class="value">${{ "{:,}".format(stats.revenue.billed) }}</div>
      <div class="sub">project invoices</div>
    </div>
    <div class="stat-card green">
      <div class="label">Collected</div>
      <div class="value">${{ "{:,}".format(stats.revenue.collected) }}</div>
      <div class="sub">received</div>
    </div>
    <div class="stat-card amber">
      <div class="label">Outstanding</div>
      <div class="value">${{ "{:,}".format(stats.revenue.outstanding) }}</div>
      <div class="sub">awaiting payment</div>
    </div>
    <div class="stat-card green">
      <div class="label">Care Plan MRR</div>
      <div class="value">${{ stats.revenue.care_mrr }}</div>
      <div class="sub">monthly recurring</div>
    </div>
  </div>

  <div class="chart-wrap">
    <h3>Revenue Breakdown</h3>
    <canvas id="revenueChart"></canvas>
  </div>
</section>

<!-- ── CLOSE RATE ────────────────────────────────────────────────────── -->
<section id="tab-closerate" class="section">
  <div class="card-grid">
    <div class="stat-card {{ 'green' if stats.close_rate >= 25 else 'amber' if stats.close_rate >= 15 else 'red' }}">
      <div class="label">Close Rate</div>
      <div class="value">{{ stats.close_rate }}%</div>
      <div class="sub">target: 25–30%</div>
    </div>
    <div class="stat-card">
      <div class="label">Emailed</div>
      <div class="value">{{ stats.emailed_count }}</div>
    </div>
    <div class="stat-card green">
      <div class="label">Closed</div>
      <div class="value">{{ stats.closed_count }}</div>
    </div>
    <div class="stat-card">
      <div class="label">Open Rate</div>
      <div class="value">{{ (stats.outreach.opened / [stats.outreach.total,1]|max * 100)|round(1) }}%</div>
      <div class="sub">{{ stats.outreach.opened }}/{{ stats.outreach.total }}</div>
    </div>
  </div>

  <div class="chart-wrap">
    <h3>Stage Drop-off</h3>
    <canvas id="dropoffChart"></canvas>
  </div>
</section>

<!-- ── CLIENTS ───────────────────────────────────────────────────────── -->
<section id="tab-clients" class="section">
  <div class="tbl-wrap">
    <table id="clients-table">
      <thead>
        <tr>
          <th onclick="sortTable('clients-table',0)">Business ↕</th>
          <th onclick="sortTable('clients-table',1)">Niche ↕</th>
          <th onclick="sortTable('clients-table',2)">Tier ↕</th>
          <th onclick="sortTable('clients-table',3)">Status ↕</th>
          <th onclick="sortTable('clients-table',4)">VPS $/mo ↕</th>
          <th>Care Plan</th>
        </tr>
      </thead>
      <tbody>
        {% for c in stats.clients %}
        <tr>
          <td>
            <strong>{{ c.business_name }}</strong>
            {% if c.domain %}<br><a href="https://{{ c.domain }}" target="_blank"
               style="color:var(--accent);font-size:12px;">{{ c.domain }}</a>{% endif %}
          </td>
          <td>{{ c.niche or '—' }}</td>
          <td>{{ c.tier or '—' }}</td>
          <td><span style="color:{{ 'var(--accent)' if c.status=='live' else 'var(--amber)' if 'build' in (c.status or '') else 'var(--muted)' }};">
            {{ c.status }}</span></td>
          <td>{{ '$' ~ c.vps_cost|int if c.vps_cost else '—' }}</td>
          <td>{{ '$' ~ c.care_plan|int ~ '/mo' if c.care_plan else 'No' }}</td>
        </tr>
        {% else %}
        <tr><td colspan="6" style="color:var(--muted);text-align:center;padding:24px;">No clients yet.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<!-- ── COSTS ────────────────────────────────────────────────────────── -->
<section id="tab-costs" class="section">
  <div class="card-grid">
    <div class="stat-card">
      <div class="label">OpenAI Spend</div>
      <div class="value">${{ stats.ai_cost }}</div>
      <div class="sub">total AI costs</div>
    </div>
    <div class="stat-card amber">
      <div class="label">VPS Costs</div>
      <div class="value">${{ stats.vps_monthly }}</div>
      <div class="sub">{{ stats.vps_count }} servers / mo</div>
    </div>
    <div class="stat-card">
      <div class="label">Stripe Fees</div>
      <div class="value">${{ (stats.revenue.collected * 0.029 + stats.closed_count * 0.30)|round(2) }}</div>
      <div class="sub">est. 2.9% + $0.30</div>
    </div>
  </div>

  <div class="chart-wrap">
    <h3>AI Cost by Operation</h3>
    <canvas id="costChart"></canvas>
  </div>

  {% if stats.cost_breakdown %}
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Operation</th><th>Cost (USD)</th></tr></thead>
      <tbody>
        {% for op, cost in stats.cost_breakdown.items() %}
        <tr><td>{{ op }}</td><td>${{ cost }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</section>

<!-- ── ROOK ──────────────────────────────────────────────────────────── -->
<section id="tab-rook" class="section">
  <div class="card-grid">
    <div class="stat-card">
      <div class="label">Calls Made</div>
      <div class="value">{{ stats.calls_attempted }}</div>
    </div>
    <div class="stat-card" style="opacity:.5;">
      <div class="label">Pick-up Rate</div>
      <div class="value">—</div>
      <div class="sub">Rook not yet live</div>
    </div>
    <div class="stat-card" style="opacity:.5;">
      <div class="label">Appts Booked</div>
      <div class="value">—</div>
      <div class="sub">via Calendly</div>
    </div>
  </div>

  {% if stats.rook %}
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Business</th><th>Phone</th><th>Date</th><th>Result</th></tr></thead>
      <tbody>
        {% for r in stats.rook %}
        <tr>
          <td>{{ r.business_name }}</td>
          <td style="font-family:monospace;font-size:12px;">{{ r.phone or '—' }}</td>
          <td style="font-size:12px;color:var(--muted);">{{ r.sent_at[:10] if r.sent_at else '—' }}</td>
          <td>{{ '<span style="color:var(--red)">Error</span>' | safe if r.error else 'Sent' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div style="text-align:center;padding:40px;color:var(--muted);">
    No Rook calls logged yet. Rook is pending FCC compliance review.
  </div>
  {% endif %}
</section>

<!-- ── PORTFOLIO ─────────────────────────────────────────────────────── -->
<section id="tab-portfolio" class="section">
  {% if stats.portfolio %}
  <div class="portfolio-grid">
    {% for p in stats.portfolio %}
    <a class="portfolio-card" href="{{ p.netlify_url }}" target="_blank">
      <div class="portfolio-thumb-placeholder">🌐</div>
      <div class="portfolio-meta">
        <strong>{{ p.business_name }}</strong>
        <span>{{ p.niche or '' }}</span>
        {% if p.domain %}
        <span style="display:block;color:var(--accent);font-size:11px;">{{ p.domain }}</span>
        {% endif %}
      </div>
    </a>
    {% endfor %}
  </div>
  {% else %}
  <div style="text-align:center;padding:40px;color:var(--muted);">
    No live portfolio sites yet.
  </div>
  {% endif %}
</section>

<!-- ── PRICE OPTIMIZER ───────────────────────────────────────────────── -->
<section id="tab-optimizer" class="section">
  <div class="chart-wrap">
    <h3>Close Rate vs. Target</h3>
    <canvas id="gaugeChart"></canvas>
  </div>

  <div class="gauge-wrap">
    <div class="gauge-value">{{ stats.close_rate }}%</div>
    <div class="gauge-label">Current close rate &bull; Target: 25–30%</div>

    {% if stats.close_rate < 25 %}
    <div class="alert warn" style="margin-top:16px;">
      <strong>Below target</strong>
      Close rate is under 25%. Consider lowering prices or adjusting outreach.
    </div>
    {% elif stats.close_rate > 30 %}
    <div class="alert success" style="margin-top:16px;">
      <strong>Above target — consider raising prices</strong>
      A >30% close rate often means you're underpriced. Test a 10–15% increase.
    </div>
    {% else %}
    <div class="alert success" style="margin-top:16px;">
      <strong>Right on target ✓</strong>
      Close rate is in the sweet spot. Hold pricing steady.
    </div>
    {% endif %}

    <div style="margin-top:20px;">
      <div style="font-size:14px;color:var(--muted);margin-bottom:8px;">
        Progress to 40-client pricing review threshold
      </div>
      <div class="progress-bar">
        <div class="progress-fill" style="width:{{ [stats.total_live / 40 * 100, 100]|min|int }}%"></div>
      </div>
      <div style="font-size:13px;color:var(--text);">
        <strong>{{ stats.total_live }}</strong> / 40 live clients
        &mdash; <strong>{{ stats.clients_to_threshold }}</strong> to go
      </div>
    </div>

    {% if stats.clients_to_threshold == 0 %}
    <div class="alert success" style="margin-top:16px;">
      <strong>🎉 Pricing report ready!</strong>
      You've hit 40 clients. Run <code>python -m src.analytics.reporter --pricing</code>
      to generate your pricing optimization report.
    </div>
    {% endif %}
  </div>
</section>

</main>

<script>
// ── Tab switching ──────────────────────────────────────────────────────────
function showTab(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  event.target.classList.add('active');
}

// ── Auto-refresh ────────────────────────────────────────────────────────────
const REFRESH_MS = 300_000; // 5 minutes
let remaining = REFRESH_MS / 1000;
const el = document.getElementById('last-refresh');
setInterval(() => {
  remaining--;
  if (remaining <= 0) location.reload();
  const m = Math.floor(remaining / 60), s = remaining % 60;
  el.textContent = `refresh in ${m}m ${s}s`;
}, 1000);

// ── Revenue chart ────────────────────────────────────────────────────────────
const rd = {{ stats.revenue | tojson }};
new Chart(document.getElementById('revenueChart'), {
  type: 'bar',
  data: {
    labels: ['Billed', 'Collected', 'Outstanding', 'Care MRR'],
    datasets: [{
      data: [rd.billed, rd.collected, rd.outstanding, rd.care_mrr],
      backgroundColor: ['#4caf50','#81c784','#ffa726','#29b6f6'],
      borderRadius: 6,
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { display: false },
               tooltip: { callbacks: { label: ctx => '$' + ctx.parsed.y.toLocaleString() } } },
    scales: {
      y: { ticks: { color: '#8fbc8f', callback: v => '$' + v.toLocaleString() },
           grid: { color: '#1e3a1e' } },
      x: { ticks: { color: '#8fbc8f' }, grid: { display: false } }
    }
  }
});

// ── Stage drop-off chart ──────────────────────────────────────────────────
const po = {{ stats.pipeline_ordered | tojson }};
new Chart(document.getElementById('dropoffChart'), {
  type: 'bar',
  data: {
    labels: po.map(s => s[0].replace(/_/g,' ')),
    datasets: [{
      data: po.map(s => s[1]),
      backgroundColor: po.map((_, i) => `hsl(${120 - i * 7}, 50%, 40%)`),
      borderRadius: 4,
    }]
  },
  options: {
    indexAxis: 'y',
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#8fbc8f' }, grid: { color: '#1e3a1e' } },
      y: { ticks: { color: '#8fbc8f', font: { size: 11 } }, grid: { display: false } }
    }
  }
});

// ── Cost breakdown chart ─────────────────────────────────────────────────
const cb = {{ stats.cost_breakdown | tojson }};
const cbKeys = Object.keys(cb), cbVals = Object.values(cb);
if (cbKeys.length) {
  new Chart(document.getElementById('costChart'), {
    type: 'doughnut',
    data: {
      labels: cbKeys,
      datasets: [{
        data: cbVals,
        backgroundColor: ['#4caf50','#81c784','#a5d6a7','#c8e6c9','#ffcc80','#ffb74d'],
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: '#8fbc8f', font: { size: 12 } } },
        tooltip: { callbacks: { label: ctx => ctx.label + ': $' + ctx.parsed } }
      }
    }
  });
}

// ── Close rate gauge (doughnut) ──────────────────────────────────────────
const cr = {{ stats.close_rate }};
new Chart(document.getElementById('gaugeChart'), {
  type: 'doughnut',
  data: {
    labels: ['Close Rate', 'Gap to 30%'],
    datasets: [{
      data: [cr, Math.max(0, 30 - cr)],
      backgroundColor: [cr >= 25 ? '#4caf50' : cr >= 15 ? '#ffa726' : '#ef5350', '#1e3a1e'],
      borderWidth: 0,
    }]
  },
  options: {
    responsive: true,
    cutout: '72%',
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: ctx => ctx.label + ': ' + ctx.parsed + '%' } }
    }
  }
});

// ── Sortable table ────────────────────────────────────────────────────────
function sortTable(id, col) {
  const tbl = document.getElementById(id), tb = tbl.querySelector('tbody');
  const rows = Array.from(tb.querySelectorAll('tr'));
  const asc = tbl.dataset.sortCol == col && tbl.dataset.sortDir == 'asc' ? false : true;
  tbl.dataset.sortCol = col; tbl.dataset.sortDir = asc ? 'asc' : 'desc';
  rows.sort((a, b) => {
    const av = a.cells[col]?.textContent.trim() || '';
    const bv = b.cells[col]?.textContent.trim() || '';
    return asc ? av.localeCompare(bv, undefined, { numeric: true })
               : bv.localeCompare(av, undefined, { numeric: true });
  });
  rows.forEach(r => tb.appendChild(r));
}
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    stats = _stats()
    return render_template_string(
        _TEMPLATE,
        stats=stats,
        dashboard_url=DASHBOARD_URL,
        portal_url=PORTAL_URL,
    )


@app.route("/api/stats")
def api_stats():
    return jsonify(_stats())


@app.route("/preview/<int:lead_id>/")
@app.route("/preview/<int:lead_id>/<path:filename>")
def preview_site(lead_id: int, filename: str = "index.html"):
    """Serve the built site files so Steele can preview before approving."""
    build_dir = _BUILD_DIR / str(lead_id)
    if not build_dir.exists():
        return f"Build for lead #{lead_id} not found.", 404
    return send_from_directory(str(build_dir), filename)


@app.route("/approve/<token>")
def route_approve(token: str):
    result = approve_build(token)
    if result["ok"]:
        lead_id = result["lead_id"]
        return render_template_string(
            _ACTION_PAGE,
            icon="✓", color="#2e7d32",
            title="Build approved!",
            body=f"The review-ready email has been sent to the client for lead #{lead_id}.",
        )
    return render_template_string(
        _ACTION_PAGE, icon="✗", color="#b71c1c",
        title="Approval failed", body=result["reason"],
    ), 400


@app.route("/reject/<token>")
def route_reject(token: str):
    result = reject_build(token)
    if result["ok"]:
        lead_id = result["lead_id"]
        return render_template_string(
            _ACTION_PAGE,
            icon="✗", color="#e65100",
            title="Revision flagged",
            body=f"Lead #{lead_id} has been flagged as revision_needed. Edit the build and re-run approval.",
        )
    return render_template_string(
        _ACTION_PAGE, icon="✗", color="#b71c1c",
        title="Rejection failed", body=result["reason"],
    ), 400


_ACTION_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Curbsite Dashboard</title>
<style>
body{margin:0;padding:40px 20px;background:#0d1a0d;color:#e8f5e9;
     font-family:Arial,sans-serif;text-align:center;}
.icon{font-size:60px;display:block;margin-bottom:16px;}
h1{font-size:24px;color:{{ color }};}
p{font-size:16px;color:#8fbc8f;margin-top:12px;}
a{color:#5cb85c;}
</style></head>
<body>
<span class="icon">{{ icon }}</span>
<h1>{{ title }}</h1>
<p>{{ body }}</p>
<p style="margin-top:24px;"><a href="/">← Back to Dashboard</a></p>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("DASHBOARD_PORT", "5050")), debug=False)
