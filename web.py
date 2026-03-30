"""
Charlie Web — serves briefs and collects feedback.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, redirect, url_for
from core.config import config
from core.state import StateManager

app = Flask(__name__)
state = StateManager()

# ── Feedback Storage ─────────────────────────────────────────────────────

FEEDBACK_PATH = config.data_dir / "feedback.json"


def load_feedback() -> dict:
    if FEEDBACK_PATH.exists():
        with open(FEEDBACK_PATH) as f:
            return json.load(f)
    return {"ratings": [], "summary": {}}


def save_feedback(feedback: dict):
    with open(FEEDBACK_PATH, "w") as f:
        json.dump(feedback, f, indent=2, default=str)


def add_rating(signal_headline: str, signal_type: str, rating: int, brief_date: str):
    feedback = load_feedback()
    feedback["ratings"].append({
        "headline": signal_headline,
        "signal_type": signal_type,
        "rating": rating,
        "brief_date": brief_date,
        "rated_at": datetime.now().isoformat(),
    })
    summary = feedback.get("summary", {})
    if signal_type not in summary:
        summary[signal_type] = {"total_ratings": 0, "sum": 0, "avg": 5.0}
    summary[signal_type]["total_ratings"] += 1
    summary[signal_type]["sum"] += rating
    summary[signal_type]["avg"] = round(summary[signal_type]["sum"] / summary[signal_type]["total_ratings"], 1)
    feedback["summary"] = summary
    save_feedback(feedback)


def get_feedback_prompt_injection() -> str:
    feedback = load_feedback()
    summary = feedback.get("summary", {})
    if not summary:
        return ""
    lines = ["## Feedback-Based Calibration",
             "Based on user ratings (1=irrelevant, 10=gold):"]
    for sig_type, data in sorted(summary.items(), key=lambda x: x[1]["avg"], reverse=True):
        if data["total_ratings"] >= 2:
            lines.append(f"- {sig_type}: {data['avg']}/10 (n={data['total_ratings']})")
    recent_low = [r for r in feedback.get("ratings", [])[-50:] if r["rating"] <= 2]
    if recent_low:
        lines.append("\nAvoid similar to:")
        for r in recent_low[-5:]:
            lines.append(f'- "{r["headline"]}" ({r["rating"]}/10)')
    recent_high = [r for r in feedback.get("ratings", [])[-50:] if r["rating"] >= 8]
    if recent_high:
        lines.append("\nMore like:")
        for r in recent_high[-5:]:
            lines.append(f'- "{r["headline"]}" ({r["rating"]}/10)')
    return "\n".join(lines)


# ── Shared Styles & Nav ──────────────────────────────────────────────────

SHARED_STYLES = """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Georgia', serif; background: #fafafa; color: #1a1a1a; line-height: 1.6; }
  .container { max-width: 680px; margin: 0 auto; padding: 40px 24px; }
  .header { border-bottom: 3px solid #1a1a1a; padding-bottom: 16px; margin-bottom: 12px; }
  .header h1 { font-size: 28px; letter-spacing: -0.5px; }
  .header .sub { font-size: 14px; color: #666; margin-top: 4px; }
  .nav { display: flex; gap: 16px; padding: 12px 0 24px 0; border-bottom: 1px solid #e0e0e0; margin-bottom: 28px; font-size: 13px; }
  .nav a { color: #3D5A80; text-decoration: none; }
  .nav a:hover { text-decoration: underline; }
  .nav a.active { color: #1a1a1a; font-weight: bold; text-decoration: none; }
  .empty { font-size: 14px; color: #999; font-style: italic; }
  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e0e0e0; font-size: 12px; color: #999; }
  a { color: #3D5A80; }
  .btn { display: inline-block; padding: 12px 24px; background: #3D5A80; color: white; border: none;
         border-radius: 4px; font-size: 15px; cursor: pointer; text-decoration: none; font-family: Georgia, serif; }
  .btn:hover { background: #2B3A4A; }
"""

def nav_html(active="brief"):
    return f"""<div class="nav">
  <a href="/" class="{'active' if active == 'brief' else ''}">The Brief</a>
  <a href="/thesis" class="{'active' if active == 'thesis' else ''}">Living Thesis</a>
  <a href="/book" class="{'active' if active == 'book' else ''}">Book Project</a>
  <a href="/archive" class="{'active' if active == 'archive' else ''}">Archive</a>
  <a href="/run" class="{'active' if active == 'run' else ''}">Run</a>
</div>"""


# ── Brief Template ───────────────────────────────────────────────────────

BRIEF_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — The Brief</title>
<style>
  """ + SHARED_STYLES + """
  .date-nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; font-size: 13px; }
  .date-nav a { color: #3D5A80; text-decoration: none; }
  .date-nav a:hover { text-decoration: underline; }
  .date-nav .current { font-weight: bold; color: #1a1a1a; }
  .date-nav .placeholder { visibility: hidden; }

  .tier { margin-bottom: 36px; }
  .tier-label { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999; margin-bottom: 8px; }
  .tier h2 { font-size: 18px; line-height: 1.4; margin-bottom: 12px; }
  .tier .body { font-size: 15px; color: #333; margin-bottom: 12px; }
  .tier .question { font-size: 14px; color: #666; font-style: italic; padding-left: 16px; border-left: 2px solid #ddd; }
  .divider { border: none; border-top: 1px solid #e0e0e0; margin: 32px 0; }

  .signal-log { margin-top: 40px; border-top: 2px solid #e0e0e0; padding-top: 24px; }
  .signal-log h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 16px; }
  .signal { margin-bottom: 20px; padding: 16px; background: #f5f5f5; border-radius: 6px; font-size: 13px; }
  .signal .sig-head { font-weight: bold; margin-bottom: 6px; font-size: 14px; }
  .signal .sig-meta { color: #888; font-size: 12px; margin-bottom: 4px; }
  .signal .sig-source { margin-top: 6px; }
  .signal .sig-source a { color: #3D5A80; text-decoration: none; font-size: 12px; }
  .signal .sig-source a:hover { text-decoration: underline; }
  .signal .sig-imp { color: #555; font-size: 12px; margin-top: 6px; }

  .rating { margin-top: 10px; display: flex; align-items: center; gap: 4px; }
  .rating-label { font-size: 11px; color: #999; margin-right: 8px; }
  .rating-btn {
    width: 28px; height: 28px; border: 1px solid #ddd; border-radius: 4px;
    background: white; cursor: pointer; font-size: 11px; color: #666;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.15s;
  }
  .rating-btn:hover { background: #3D5A80; color: white; border-color: #3D5A80; }
  .rating-btn.selected { background: #3D5A80; color: white; border-color: #3D5A80; }
  .rating-btn.low.selected { background: #c0392b; border-color: #c0392b; }
  .rating-btn.mid.selected { background: #7f8c8d; border-color: #7f8c8d; }
  .rating-btn.high.selected { background: #27ae60; border-color: #27ae60; }

  @media print {
    body { background: white; }
    .container { padding: 20px 0; }
    .rating, .nav, .date-nav { display: none; }
  }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Brief</h1>
    <div class="sub">{{ date_display }}</div>
  </div>

  {{ nav | safe }}

  {% if prev_date or next_date %}
  <div class="date-nav">
    {% if prev_date %}
    <a href="/brief/{{ prev_date }}">← {{ prev_date }}</a>
    {% else %}
    <span class="placeholder">←</span>
    {% endif %}
    <span class="current">{{ current_date }}</span>
    {% if next_date %}
    <a href="/brief/{{ next_date }}">{{ next_date }} →</a>
    {% else %}
    <span class="placeholder">→</span>
    {% endif %}
  </div>
  {% endif %}

  {% if brief %}
  {% set tiers = [
    ('The Signal', brief.get('tier_1')),
    ('The Bullshit Flag', brief.get('tier_2')),
    ('Your World', brief.get('tier_3'))
  ] %}

  {% for label, tier in tiers %}
  <div class="tier">
    <div class="tier-label">{{ label }}</div>
    {% if tier %}
    <h2>{{ tier.headline }}</h2>
    <div class="body">{{ tier.body }}</div>
    {% if tier.open_question %}
    <div class="question">→ {{ tier.open_question }}</div>
    {% endif %}
    {% else %}
    <p class="empty">Nothing qualified today.</p>
    {% endif %}
  </div>
  <hr class="divider">
  {% endfor %}

  {% if signals %}
  <div class="signal-log">
    <h3>Signal Log ({{ signals|length }} signals)</h3>
    {% for s in signals %}
    <div class="signal" id="signal-{{ loop.index }}">
      <div class="sig-head">{{ loop.index }}. [{{ s.signal_type | default('unknown') }}] {{ s.headline | default('No headline') }}</div>
      <div class="sig-meta">
        Confidence: {{ s.confidence | default('?') }} |
        Weight: {{ s.implication_weight | default('?') }} |
        {{ s.source | default('') }}
        {% if s.thesis_force and s.thesis_force != 'none' %}
        | Force: {{ s.thesis_force }}
        {% endif %}
      </div>
      {% if s.source_url %}
      <div class="sig-source">
        <a href="{{ s.source_url }}" target="_blank" rel="noopener">{{ s.source_url | truncate(80) }}</a>
      </div>
      {% endif %}
      {% if s.forward_implications %}
      <div class="sig-imp">
        {% for imp in s.forward_implications[:3] %}
        → {{ imp }}<br>
        {% endfor %}
      </div>
      {% endif %}
      <div class="rating" data-headline="{{ s.headline | default('') | e }}" data-type="{{ s.signal_type | default('other') }}">
        <span class="rating-label">Relevance:</span>
        {% for n in range(1, 11) %}
        <button class="rating-btn {{ 'low' if n <= 3 else ('mid' if n <= 6 else 'high') }}"
                onclick="rate(this, {{ n }})" title="{{ n }}">{{ n }}</button>
        {% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% else %}
  <p class="empty">No brief available for this date.</p>
  <p style="margin-top: 16px;"><a href="/run">Run The Brief now →</a></p>
  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>

<script>
function rate(btn, rating) {
  const container = btn.closest('.rating');
  const headline = container.dataset.headline;
  const sigType = container.dataset.type;
  container.querySelectorAll('.rating-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      headline: headline,
      signal_type: sigType,
      rating: rating,
      brief_date: '{{ current_date }}'
    })
  });
}
</script>
</body>
</html>"""


# ── Archive Template ─────────────────────────────────────────────────────

ARCHIVE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Archive</title>
<style>
  """ + SHARED_STYLES + """
  .brief-card { margin-bottom: 24px; padding: 20px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .brief-card:hover { border-color: #3D5A80; }
  .brief-card a { text-decoration: none; color: inherit; display: block; }
  .brief-date { font-size: 13px; color: #999; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
  .brief-signal { font-size: 16px; font-weight: bold; color: #1a1a1a; margin-bottom: 6px; line-height: 1.3; }
  .brief-tiers { font-size: 13px; color: #666; }
  .brief-tiers .tier-item { margin-bottom: 4px; }
  .brief-tiers .tier-label { color: #999; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
  .brief-meta { font-size: 12px; color: #999; margin-top: 8px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Brief</h1>
    <div class="sub">Archive</div>
  </div>

  {{ nav | safe }}

  {% if briefs %}
  {% for b in briefs %}
  <div class="brief-card">
    <a href="/brief/{{ b.date }}">
      <div class="brief-date">{{ b.date_display }}</div>
      {% if b.tier_1 %}
      <div class="brief-signal">{{ b.tier_1 }}</div>
      {% else %}
      <div class="brief-signal" style="color: #999;">No signal generated</div>
      {% endif %}
      <div class="brief-tiers">
        {% if b.tier_2 %}
        <div class="tier-item"><span class="tier-label">Bullshit Flag:</span> {{ b.tier_2 }}</div>
        {% endif %}
        {% if b.tier_3 %}
        <div class="tier-item"><span class="tier-label">Your World:</span> {{ b.tier_3 }}</div>
        {% endif %}
      </div>
      <div class="brief-meta">{{ b.signal_count }} signals ingested</div>
    </a>
  </div>
  {% endfor %}
  {% else %}
  <p class="empty">No briefs have been generated yet. <a href="/run">Run the first one →</a></p>
  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
</body>
</html>"""


# ── Run Template ─────────────────────────────────────────────────────────

RUN_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Run Pipeline</title>
<style>
  """ + SHARED_STYLES + """
  .run-box { margin-top: 24px; padding: 24px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .run-box p { font-size: 15px; color: #333; margin-bottom: 16px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Brief</h1>
    <div class="sub">Run Pipeline</div>
  </div>

  {{ nav | safe }}

  <div class="run-box">
    <p>Run the full daily pipeline: ingestion, analysis, brief generation. Takes ~10 minutes.</p>
    <form method="POST">
      <button type="submit" class="btn">Run Now</button>
    </form>
  </div>

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
</body>
</html>"""

RUNNING_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Running</title>
<meta http-equiv="refresh" content="600;url=/">
<style>
  """ + SHARED_STYLES + """
  .status-box { margin-top: 24px; padding: 24px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .status-box p { font-size: 15px; color: #333; margin-bottom: 12px; }
  .status-box .hint { font-size: 13px; color: #999; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Brief</h1>
    <div class="sub">Pipeline Running</div>
  </div>

  {{ nav | safe }}

  <div class="status-box">
    <p>The daily pipeline is running in the background.</p>
    <p class="hint">This page will redirect to The Brief in 10 minutes, or <a href="/">check now</a>.</p>
  </div>

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")], reverse=True)
    if available:
        return redirect(url_for("show_brief", brief_date=available[0]))
    return render_template_string(BRIEF_TEMPLATE, brief=None, signals=[],
                                 date_display="No briefs yet", nav=nav_html("brief"),
                                 current_date="", prev_date=None, next_date=None)


@app.route("/archive")
def archive():
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")], reverse=True)

    briefs_summary = []
    for brief_date in available:
        brief_path = briefs_dir / f"{brief_date}.json"
        entry = {"date": brief_date, "tier_1": None, "tier_2": None, "tier_3": None, "signal_count": 0}
        try:
            d = date.fromisoformat(brief_date)
            entry["date_display"] = d.strftime("%A, %B %d, %Y")
        except ValueError:
            entry["date_display"] = brief_date

        try:
            with open(brief_path) as f:
                data = json.load(f)
                brief = data.get("brief", data)
                if brief.get("tier_1"):
                    entry["tier_1"] = brief["tier_1"].get("headline", "")
                if brief.get("tier_2"):
                    entry["tier_2"] = brief["tier_2"].get("headline", "")
                if brief.get("tier_3"):
                    entry["tier_3"] = brief["tier_3"].get("headline", "")
        except (json.JSONDecodeError, KeyError):
            pass

        try:
            signals = state.load_signals(date.fromisoformat(brief_date))
            entry["signal_count"] = len(signals)
        except ValueError:
            pass

        briefs_summary.append(entry)

    return render_template_string(ARCHIVE_TEMPLATE, briefs=briefs_summary, nav=nav_html("archive"))


@app.route("/brief/<brief_date>")
def show_brief(brief_date):
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")])

    # Find prev/next dates
    prev_date = None
    next_date = None
    if brief_date in available:
        idx = available.index(brief_date)
        if idx > 0:
            prev_date = available[idx - 1]
        if idx < len(available) - 1:
            next_date = available[idx + 1]

    # Load brief
    brief_path = briefs_dir / f"{brief_date}.json"
    brief = None
    if brief_path.exists():
        with open(brief_path) as f:
            data = json.load(f)
            brief = data.get("brief", data)

    # Load signals
    signals = []
    try:
        signals = state.load_signals(date.fromisoformat(brief_date))
    except ValueError:
        pass

    # Format date
    try:
        d = date.fromisoformat(brief_date)
        date_display = d.strftime("%A, %B %d, %Y")
    except ValueError:
        date_display = brief_date

    return render_template_string(BRIEF_TEMPLATE,
                                 brief=brief, signals=signals,
                                 date_display=date_display,
                                 nav=nav_html("brief"),
                                 current_date=brief_date,
                                 prev_date=prev_date,
                                 next_date=next_date)


# ── Thesis Routes ────────────────────────────────────────────────────────

THESIS_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — The Living Thesis</title>
<style>
  """ + SHARED_STYLES + """
  .thesis-meta { font-size: 12px; color: #999; margin-bottom: 28px; }
  .force { margin-bottom: 36px; padding: 20px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .force-label { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999; margin-bottom: 8px; }
  .force h2 { font-size: 18px; margin-bottom: 12px; color: #1a1a1a; }
  .force .summary { font-size: 15px; color: #333; margin-bottom: 16px; line-height: 1.6; }
  .evidence-list { margin: 0; padding: 0; list-style: none; }
  .evidence-list li { font-size: 13px; color: #555; padding: 6px 0 6px 16px; border-left: 2px solid #e0e0e0; margin-bottom: 6px; }
  .evidence-list li.strong { border-left-color: #27ae60; }
  .gaps { margin-top: 16px; }
  .gaps h4 { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #c0392b; margin-bottom: 8px; }
  .gaps li { font-size: 13px; color: #888; padding: 4px 0; }

  .claims { margin-top: 36px; border-top: 2px solid #e0e0e0; padding-top: 24px; }
  .claims h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 16px; }
  .claim { margin-bottom: 16px; padding: 16px; background: #f5f5f5; border-radius: 6px; }
  .claim .claim-text { font-size: 15px; color: #1a1a1a; margin-bottom: 6px; }
  .claim .claim-meta { font-size: 12px; color: #999; }
  .confidence-high { border-left: 3px solid #27ae60; }
  .confidence-medium-high { border-left: 3px solid #f39c12; }
  .confidence-medium { border-left: 3px solid #e67e22; }
  .confidence-low { border-left: 3px solid #c0392b; }

  .ip-landscape { margin-top: 36px; border-top: 2px solid #e0e0e0; padding-top: 24px; }
  .ip-landscape h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 16px; }
  .ip-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .ip-item { padding: 12px; background: #f5f5f5; border-radius: 4px; font-size: 13px; }
  .ip-item .ip-name { font-weight: bold; margin-bottom: 4px; }
  .ip-item .ip-status { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
  .ip-item .ip-notes { color: #666; font-size: 12px; }
  .status-saturating { color: #c0392b; }
  .status-fatigued { color: #e67e22; }
  .status-accelerating { color: #27ae60; }
  .status-early { color: #3D5A80; }
  .status-emerging { color: #3D5A80; }
  .status-nascent { color: #999; }
  .status-most_mature { color: #27ae60; }
  .status-stable { color: #7f8c8d; }
  .status-heavily_mined { color: #e67e22; }
  .status-evolved { color: #f39c12; }
  .status-uncertain { color: #999; }

  @media (max-width: 500px) { .ip-grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Living Thesis</h1>
    <div class="sub">Entertainment Industry Restructuring</div>
  </div>

  {{ nav | safe }}

  {% if thesis %}
  <div class="thesis-meta">Version {{ thesis.version | default(1) }} · Updated {{ thesis.updated_at | default('unknown') }}</div>

  <p style="font-size: 15px; color: #333; margin-bottom: 32px; line-height: 1.7;">{{ thesis.core_argument }}</p>

  {% for force_key, force_label in [('supply_exhaustion', 'Supply Exhaustion'), ('demand_migration', 'Demand Migration'), ('discovery_bridge', 'The Discovery Bridge')] %}
  {% set force = thesis.forces.get(force_key, {}) %}
  <div class="force">
    <div class="force-label">Force {{ loop.index }}</div>
    <h2>{{ force_label }}</h2>
    <div class="summary">{{ force.get('summary', '') }}</div>
    {% if force.get('evidence') %}
    <ul class="evidence-list">
      {% for e in force.evidence %}
      <li class="strong">{{ e }}</li>
      {% endfor %}
    </ul>
    {% endif %}
    {% if force.get('gaps') %}
    <div class="gaps">
      <h4>Research Gaps</h4>
      <ul class="evidence-list">
        {% for g in force.gaps %}
        <li>{{ g }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}
    <div class="claim-meta" style="margin-top: 12px;">Confidence: {{ force.get('confidence', '?') }}</div>
  </div>
  {% endfor %}

  {% if thesis.get('claims') %}
  <div class="claims">
    <h3>Core Claims</h3>
    {% for c in thesis.claims %}
    <div class="claim confidence-{{ c.get('confidence', 'medium') | replace(' ', '-') }}">
      <div class="claim-text">{{ c.claim }}</div>
      <div class="claim-meta">Confidence: {{ c.confidence }} · Force: {{ c.get('force', 'all') }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if thesis.get('ip_landscape') %}
  <div class="ip-landscape">
    <h3>IP Landscape — Traditional</h3>
    <div class="ip-grid">
      {% for key, val in thesis.ip_landscape.get('traditional', {}).items() %}
      <div class="ip-item">
        <div class="ip-name">{{ key | replace('_', ' ') | title }}</div>
        <div class="ip-status status-{{ val.status }}">{{ val.status | replace('_', ' ') }}</div>
        <div class="ip-notes">{{ val.notes }}</div>
      </div>
      {% endfor %}
    </div>

    <h3 style="margin-top: 24px;">IP Landscape — Creator-Driven</h3>
    <div class="ip-grid">
      {% for key, val in thesis.ip_landscape.get('creator_driven', {}).items() %}
      <div class="ip-item">
        <div class="ip-name">{{ key | replace('_', ' ') | title }}</div>
        <div class="ip-status status-{{ val.status }}">{{ val.status | replace('_', ' ') }}</div>
        <div class="ip-notes">{{ val.notes }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% else %}
  <p class="empty">No thesis document has been seeded yet.</p>
  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
</body>
</html>"""


BOOK_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Book Project</title>
<style>
  """ + SHARED_STYLES + """
  .book-status { font-size: 14px; color: #333; margin-bottom: 28px; padding: 16px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .book-status strong { color: #1a1a1a; }

  .chapter { margin-bottom: 20px; padding: 20px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .chapter:hover { border-color: #3D5A80; }
  .chapter-num { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999; margin-bottom: 6px; }
  .chapter h2 { font-size: 17px; margin-bottom: 8px; color: #1a1a1a; }
  .chapter .focus { font-size: 14px; color: #555; line-height: 1.5; margin-bottom: 10px; }
  .chapter .ch-status { font-size: 12px; padding: 3px 10px; border-radius: 12px; display: inline-block; }
  .ch-complete { background: #d5f5e3; color: #27ae60; }
  .ch-in-progress { background: #fef9e7; color: #f39c12; }
  .ch-not-started { background: #f2f3f4; color: #999; }

  .exec-section { margin-top: 36px; border-top: 2px solid #e0e0e0; padding-top: 24px; }
  .exec-section h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 16px; }
  .exec { margin-bottom: 12px; padding: 12px 16px; background: #f5f5f5; border-radius: 4px; font-size: 13px; }
  .exec .exec-name { font-weight: bold; margin-bottom: 2px; }
  .exec .exec-detail { color: #666; font-size: 12px; }

  .questions { margin-top: 36px; border-top: 2px solid #e0e0e0; padding-top: 24px; }
  .questions h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 16px; }
  .question-item { font-size: 14px; color: #333; padding: 8px 0 8px 16px; border-left: 2px solid #3D5A80; margin-bottom: 8px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Book Project</h1>
    <div class="sub">{{ thesis.book_project.get('working_title', 'Working Title TBD') if thesis and thesis.get('book_project') else 'TBD' }}</div>
  </div>

  {{ nav | safe }}

  {% if thesis and thesis.get('book_project') %}
  {% set book = thesis.book_project %}

  <div class="book-status">
    <strong>Status:</strong> {{ book.get('status', 'unknown') | replace('_', ' ') | title }}
  </div>

  {% if book.get('chapter_outline') %}
  {% for ch in book.chapter_outline %}
  <div class="chapter">
    <div class="chapter-num">Chapter {{ ch.chapter }}</div>
    <h2>{{ ch.title }}</h2>
    <div class="focus">{{ ch.focus }}</div>
    {% if ch.status == 'lit_review_complete' %}
    <span class="ch-status ch-complete">Lit Review Complete</span>
    {% elif ch.status == 'research_in_progress' %}
    <span class="ch-status ch-in-progress">Research In Progress</span>
    {% else %}
    <span class="ch-status ch-not-started">Not Started</span>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}

  {% if thesis.get('development_function') %}
  <div class="exec-section">
    <h3>Tracked Development Executives</h3>
    {% for exec in thesis.development_function.get('tracked_executives', []) %}
    <div class="exec">
      <div class="exec-name">{{ exec.name }} — {{ exec.title }}</div>
      <div class="exec-detail">{{ exec.company }}{% if exec.get('background') %} · Previously: {{ exec.background }}{% endif %}</div>
      {% if exec.get('track_record') %}
      <div class="exec-detail">Track record: {{ exec.track_record }}</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>

  <div class="questions">
    <h3>Key Research Questions</h3>
    {% for q in thesis.development_function.get('key_questions', []) %}
    <div class="question-item">{{ q }}</div>
    {% endfor %}
  </div>
  {% endif %}

  {% else %}
  <p class="empty">No book project data available.</p>
  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
</body>
</html>"""


@app.route("/thesis")
def show_thesis():
    thesis = state.load_thesis()
    return render_template_string(THESIS_TEMPLATE, thesis=thesis, nav=nav_html("thesis"))


@app.route("/book")
def show_book():
    thesis = state.load_thesis()
    return render_template_string(BOOK_TEMPLATE, thesis=thesis, nav=nav_html("book"))


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    data = request.json
    add_rating(
        signal_headline=data.get("headline", ""),
        signal_type=data.get("signal_type", "other"),
        rating=int(data.get("rating", 5)),
        brief_date=data.get("brief_date", ""),
    )
    return jsonify({"status": "ok"})


@app.route("/api/feedback/summary")
def feedback_summary():
    feedback = load_feedback()
    return jsonify(feedback.get("summary", {}))


@app.route("/run", methods=["GET", "POST"])
def run_pipeline():
    if request.method == "GET":
        return render_template_string(RUN_TEMPLATE, nav=nav_html("run"))

    import threading
    def _run():
        try:
            from orchestrator import run_daily_pipeline
            run_daily_pipeline()
        except Exception as e:
            print(f"[Web] Pipeline error: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return render_template_string(RUNNING_TEMPLATE, nav=nav_html("run"))


# ── Scheduler ────────────────────────────────────────────────────────────

def start_scheduler():
    import threading
    import time as _time
    from datetime import datetime as _dt, timedelta

    def _scheduler_loop():
        brief_hour = int(os.environ.get("BRIEF_HOUR", "6"))
        thesis_day = int(os.environ.get("THESIS_DAY", "0"))
        tz = os.environ.get("BRIEF_TIMEZONE", "America/Los_Angeles")

        print(f"[Scheduler] Started. Brief daily at {brief_hour}:00 {tz}. Thesis Mondays at {brief_hour + 1}:00.")

        last_brief_date = None
        last_thesis_date = None

        while True:
            try:
                utc_now = _dt.utcnow()
                pacific_offset = timedelta(hours=-7)
                local_now = utc_now + pacific_offset
                today = local_now.date()
                current_hour = local_now.hour

                if current_hour >= brief_hour and last_brief_date != today:
                    print(f"[Scheduler] Triggering daily brief for {today}")
                    last_brief_date = today
                    try:
                        from orchestrator import run_daily_pipeline
                        run_daily_pipeline()
                    except Exception as e:
                        print(f"[Scheduler] Brief error: {e}")

                if local_now.weekday() == thesis_day and current_hour >= brief_hour + 1 and last_thesis_date != today:
                    print(f"[Scheduler] Triggering weekly thesis for {today}")
                    last_thesis_date = today
                    try:
                        from orchestrator import run_thesis_pipeline
                        run_thesis_pipeline()
                    except Exception as e:
                        print(f"[Scheduler] Thesis error: {e}")

            except Exception as e:
                print(f"[Scheduler] Loop error: {e}")

            _time.sleep(300)

    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()


# ── Entry Point ──────────────────────────────────────────────────────────

def seed_data():
    """Copy seed files into the data volume if they don't already exist."""
    import shutil
    seed_dir = Path(__file__).parent / "seed"
    print(f"[Seed] Looking for seed dir at: {seed_dir} (exists: {seed_dir.exists()})")
    print(f"[Seed] Data dir is: {config.data_dir} (exists: {config.data_dir.exists()})")
    if not seed_dir.exists():
        print("[Seed] No seed directory found, skipping")
        return

    for src in seed_dir.rglob("*"):
        if src.is_file():
            rel = src.relative_to(seed_dir)
            dest = config.data_dir / rel
            print(f"[Seed] {rel} → {dest} (exists: {dest.exists()})")
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                print(f"[Seed] ✓ Copied {rel}")
            else:
                print(f"[Seed] ✗ Already exists, skipping")


@app.route("/seed")
def force_seed():
    """Force re-seed from seed directory, overwriting existing files."""
    import shutil
    seed_dir = Path(__file__).parent / "seed"
    if not seed_dir.exists():
        return f"No seed directory at {seed_dir}"

    results = []
    for src in seed_dir.rglob("*"):
        if src.is_file():
            rel = src.relative_to(seed_dir)
            dest = config.data_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            results.append(f"Copied {rel} → {dest}")

    return "<br>".join(results) if results else "No files to seed"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    seed_data()
    start_scheduler()
    app.run(host="0.0.0.0", port=port, debug=False)