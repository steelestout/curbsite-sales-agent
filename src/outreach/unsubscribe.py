"""
Flask Blueprint — handles one-click unsubscribe link clicks.

Mount on the dashboard app (src/dashboard/app.py):
    from src.outreach.unsubscribe import unsub_bp
    app.register_blueprint(unsub_bp)

Endpoint: GET /unsubscribe?t=<hmac_token>&lid=<lead_id>

On a valid click:
  - Lead is marked 'unsubscribed' in the CRM
  - Subsequent send_email() calls to this lead are silently blocked
"""

import logging

from flask import Blueprint, request, render_template_string

from src.outreach.compliance import verify_unsubscribe_token, mark_unsubscribed

log = logging.getLogger(__name__)

unsub_bp = Blueprint("unsubscribe", __name__)

_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ title }}</title>
<style>
body{margin:0;padding:60px 20px;background:#0d1a0d;color:#e8f5e9;
     font-family:Arial,sans-serif;text-align:center;}
h1{font-size:24px;color:{{ color }};}
p{font-size:16px;color:#8fbc8f;margin-top:12px;line-height:1.6;}
</style>
</head><body>
<h1>{{ title }}</h1>
<p>{{ body }}</p>
</body></html>"""


@unsub_bp.route("/unsubscribe")
def unsubscribe():
    token = request.args.get("t", "")
    try:
        lead_id = int(request.args.get("lid", "0"))
    except (ValueError, TypeError):
        lead_id = 0

    if not lead_id or not token:
        return render_template_string(
            _PAGE, color="#ef5350",
            title="Invalid unsubscribe link",
            body="This link is not valid. If you believe this is an error, reply directly to the email.",
        ), 400

    if not verify_unsubscribe_token(token, lead_id):
        return render_template_string(
            _PAGE, color="#ef5350",
            title="Invalid unsubscribe link",
            body="This link appears to be invalid or expired. Reply directly to the email to opt out.",
        ), 400

    mark_unsubscribed(lead_id)
    log.info("Lead #%d unsubscribed via web link.", lead_id)

    return render_template_string(
        _PAGE, color="#5cb85c",
        title="You're unsubscribed",
        body=(
            "You've been removed from our list and will not receive any further emails from Curbsite.<br>"
            "If you change your mind, feel free to reach out at any time."
        ),
    )
