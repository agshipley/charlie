"""
Charlie Web — serves briefs and collects feedback.
"""
import json
import os
import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
import re
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, send_file
from core.config import config
from core.state import StateManager
from core.logging import configure_logging, get_logger
from core.field_extract import extract_artifact
from agents.acknowledge import run_acknowledge, load_acknowledgment
from agents.oven import run_oven

configure_logging()
_log = get_logger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB upload limit
state = StateManager()
_log.info("app_started", mode="web")


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
        summary[signal_type] = {"count": 0, "total": 0, "avg": 0}
    summary[signal_type]["count"] += 1
    summary[signal_type]["total"] += rating
    summary[signal_type]["avg"] = round(summary[signal_type]["total"] / summary[signal_type]["count"], 2)
    feedback["summary"] = summary
    save_feedback(feedback)


# ── Shared Nav ───────────────────────────────────────────────────────────

def nav_html(active: str) -> str:
    return f"""<div class="nav">
  <a href="/" class="{'active' if active == 'brief' else ''}">The Morning Loaf</a>
  <a href="/companion" class="{'active' if active == 'companion' else ''}">Companion</a>
  <a href="/thesis" class="{'active' if active == 'thesis' else ''}">Far Mar</a>
  <a href="/field" class="{'active' if active == 'field' else ''}">The Field</a>
  <a href="/oven" class="{'active' if active == 'oven' else ''}">The Oven</a>
  <a href="/archive" class="{'active' if active == 'archive' else ''}">Archive</a>
  <a href="/run" class="{'active' if active == 'run' else ''}">Run</a>
</div>"""


# ── Shared Styles ────────────────────────────────────────────────────────

SHARED_STYLES = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f0; color: #1a1a1a; }
  .container { max-width: 680px; margin: 0 auto; padding: 40px 20px; }
  .header { margin-bottom: 32px; }
  .header h1 { font-size: 22px; font-weight: 600; margin-bottom: 4px; }
  .header .sub { font-size: 14px; color: #999; }
  .nav { display: flex; gap: 20px; margin-bottom: 32px; flex-wrap: wrap; }
  .nav a { font-size: 13px; color: #666; text-decoration: none; }
  .nav a:hover { color: #1a1a1a; }
  .nav a.active { color: #1a1a1a; font-weight: 600; }
  .empty { color: #999; font-size: 14px; font-style: italic; }
  .footer { margin-top: 60px; font-size: 12px; color: #bbb; text-align: center; }
  .btn { padding: 10px 20px; background: #1a1a1a; color: white; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
  .btn:hover { background: #333; }
"""


# ── Brief Template ───────────────────────────────────────────────────────

BRIEF_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — The Morning Loaf</title>
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

  .adversary-section { margin-top: 40px; border-top: 2px solid #1a1a1a; padding-top: 24px; }
  .adv-title { font-size: 13px; text-transform: uppercase; letter-spacing: 2px; color: #1a1a1a; font-weight: 600; margin-bottom: 4px; }
  .adv-sub { font-size: 12px; color: #999; margin-bottom: 16px; }
  .adv-summary { font-size: 14px; color: #555; font-style: italic; margin-bottom: 20px; line-height: 1.5; }
  .adv-category { margin-bottom: 16px; }
  .adv-cat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #aaa; margin-bottom: 8px; }
  .adv-finding { padding: 12px 14px; background: #f8f8f6; border-left: 3px solid #ccc; margin-bottom: 8px; }
  .adv-citation { font-size: 13px; color: #333; font-style: italic; margin-bottom: 4px; }
  .adv-meta { font-size: 11px; color: #aaa; margin-bottom: 6px; }
  .adv-critique { font-size: 13px; color: #555; line-height: 1.5; }
  @media print {
    body { background: white; }
    .container { padding: 20px 0; }
    .rating, .nav, .date-nav { display: none; }
  }
</style>
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Morning Loaf</h1>
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

  <div class="adversary-section">
    <div class="adv-title">Adversary</div>
    <div class="adv-sub">What this brief might be getting wrong</div>
    {% if not adversary %}
    <p class="empty">Adversary: no output for this date.</p>
    {% elif adversary.null_finding %}
    <p class="empty">Adversary: no findings today.</p>
    {% else %}
    {% if adversary.summary %}
    <p class="adv-summary">{{ adversary.summary }}</p>
    {% endif %}
    {% set adv_categories = [
      ('flattery', 'Flattery'),
      ('pattern_exhaustion', 'Pattern Exhaustion'),
      ('inference_theater', 'Inference Theater'),
      ('missing_story', 'Missing Story'),
      ('comfortable_framing', 'Comfortable Framing')
    ] %}
    {% for cat_key, cat_label in adv_categories %}
    {% set cat_items = adversary.findings.get(cat_key, []) %}
    {% if cat_items %}
    <div class="adv-category">
      <div class="adv-cat-label">{{ cat_label }} ({{ cat_items|length }})</div>
      {% for item in cat_items %}
      <div class="adv-finding">
        {% if cat_key == 'flattery' %}
        <div class="adv-citation">"{{ item.citation }}"</div>
        <div class="adv-meta">Tier: {{ item.tier }}{% if item.prior_session_id %} · Session: {{ item.prior_session_id }}{% endif %}</div>
        {% elif cat_key == 'pattern_exhaustion' %}
        <div class="adv-citation">{{ item.pattern }}</div>
        <div class="adv-meta">{{ item.occurrences }}× in {{ item.window_days }} days</div>
        {% elif cat_key == 'inference_theater' %}
        <div class="adv-citation">"{{ item.claim }}"</div>
        <div class="adv-meta">Signal: {{ item.underlying_signal }}</div>
        {% elif cat_key == 'missing_story' %}
        <div class="adv-citation">Signal: {{ item.signal_reference }}</div>
        <div class="adv-meta">Brief said: {{ item.declined_reading }}</div>
        {% elif cat_key == 'comfortable_framing' %}
        <div class="adv-citation">"{{ item.phrase }}"</div>
        <div class="adv-meta">Tier: {{ item.tier }}</div>
        {% endif %}
        <div class="adv-critique">{{ item.critique }}</div>
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% endfor %}
    {% endif %}
  </div>

  {% else %}
  <p class="empty">No brief available for this date.</p>
  <p style="margin-top: 16px;"><a href="/run">Run The Morning Loaf now →</a></p>
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
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Morning Loaf</h1>
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
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Morning Loaf</h1>
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
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Morning Loaf</h1>
    <div class="sub">Pipeline Running</div>
  </div>

  {{ nav | safe }}

  <div class="status-box">
    <p>The daily pipeline is running in the background.</p>
    <p class="hint">This page will redirect to The Morning Loaf in 10 minutes, or <a href="/">check now</a>.</p>
  </div>

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
</body>
</html>"""


# ── Companion Template ───────────────────────────────────────────────────

COMPANION_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Companion</title>
<style>
  """ + SHARED_STYLES + """
  .companion-intro { font-size: 14px; color: #666; margin-bottom: 28px; line-height: 1.6; }
  .tier-block { margin-bottom: 40px; padding: 24px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .tier-label { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999; margin-bottom: 8px; }
  .tier-headline { font-size: 18px; font-weight: bold; color: #1a1a1a; margin-bottom: 10px; line-height: 1.4; }
  .tier-question { font-size: 14px; color: #666; font-style: italic; padding-left: 16px; border-left: 2px solid #ddd; margin-bottom: 24px; }
  .field-label { font-size: 13px; color: #444; margin-bottom: 6px; display: block; font-weight: bold; }
  .field-hint { font-size: 12px; color: #999; margin-bottom: 8px; display: block; }
  textarea { width: 100%; min-height: 100px; padding: 10px; border: 1px solid #ddd; border-radius: 4px;
             font-family: Georgia, serif; font-size: 14px; color: #1a1a1a; resize: vertical; }
  textarea:focus { outline: none; border-color: #3D5A80; }
  .radio-group { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
  .radio-group label { font-size: 14px; color: #333; cursor: pointer; display: flex; align-items: center; gap: 8px; }
  .radio-group input[type="radio"] { accent-color: #3D5A80; }
  select { width: 100%; padding: 8px 10px; border: 1px solid #ddd; border-radius: 4px;
           font-family: Georgia, serif; font-size: 14px; color: #1a1a1a; background: white; }
  select:focus { outline: none; border-color: #3D5A80; }
  input[type="text"] { width: 100%; padding: 8px 10px; border: 1px solid #ddd; border-radius: 4px;
                       font-family: Georgia, serif; font-size: 14px; color: #1a1a1a; }
  input[type="text"]:focus { outline: none; border-color: #3D5A80; }
  .field-group { margin-bottom: 20px; }
  .confidence-row { display: flex; gap: 20px; }
  .confidence-row label { font-size: 14px; color: #333; cursor: pointer; display: flex; align-items: center; gap: 6px; }
  .submit-btn { margin-top: 8px; padding: 10px 22px; background: #3D5A80; color: white; border: none;
                border-radius: 4px; font-size: 14px; cursor: pointer; font-family: Georgia, serif; }
  .submit-btn:hover { background: #2B3A4A; }
  .submit-btn:disabled { background: #aaa; cursor: default; }
  .confirmation { margin-top: 14px; padding: 10px 14px; background: #d5f5e3; color: #1a7a45;
                  border-radius: 4px; font-size: 14px; display: none; }
  .error-msg { margin-top: 14px; padding: 10px 14px; background: #fde8e8; color: #c0392b;
               border-radius: 4px; font-size: 14px; display: none; }
  .empty-tier { font-size: 14px; color: #999; font-style: italic; }
  .dc-toggle-row { display: flex; align-items: center; gap: 12px; margin-bottom: 32px; }
  .dc-toggle-btn { padding: 8px 16px; background: #f5f5f0; color: #666; border: 1px solid #ddd;
                   border-radius: 4px; font-size: 13px; cursor: pointer; }
  .dc-toggle-btn:hover { background: #ebebeb; }
  .dc-toggle-btn.dc-on { background: #1a1a1a; color: white; border-color: #1a1a1a; }
  .dc-toggle-hint { font-size: 12px; color: #bbb; }
  .dc-wrap { margin-top: 8px; }
  .dc-header-bar { padding: 20px 24px; background: #1a1a1a; color: white; border-radius: 6px 6px 0 0; }
  .dc-header-title { font-size: 12px; text-transform: uppercase; letter-spacing: 2px; font-weight: 600; margin-bottom: 8px; }
  .dc-header-sub { font-size: 13px; color: #aaa; line-height: 1.5; }
  .dc-body { border: 1px solid #1a1a1a; border-top: none; border-radius: 0 0 6px 6px; padding: 20px 24px; background: white; }
  .dc-summary { font-size: 14px; color: #555; font-style: italic; margin-bottom: 20px; line-height: 1.5; }
  .dc-cat-header { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999;
                   margin-top: 20px; margin-bottom: 10px; font-weight: 600; }
  .dc-no-findings { font-size: 13px; color: #bbb; font-style: italic; margin-bottom: 8px; }
  .dc-null { font-size: 14px; color: #999; font-style: italic; }
  .dc-card { border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px; margin-bottom: 12px; background: #fafaf8; }
  .dc-card-content { margin-bottom: 14px; }
  .dc-citation { font-size: 14px; color: #1a1a1a; font-style: italic; margin-bottom: 4px; }
  .dc-item-meta { font-size: 11px; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }
  .dc-critique { font-size: 14px; color: #333; line-height: 1.5; }
  .dc-radios { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
  .dc-radios label { font-size: 14px; color: #333; cursor: pointer; display: flex; align-items: center; gap: 8px; }
  .dc-radios input[type="radio"] { accent-color: #1a1a1a; }
  .dc-note { width: 100%; min-height: 56px; padding: 8px 10px; border: 1px solid #ddd; border-radius: 4px;
             font-family: Georgia, serif; font-size: 13px; color: #1a1a1a; resize: vertical; margin-bottom: 10px; }
  .dc-note:focus { outline: none; border-color: #1a1a1a; }
  .dc-submit-btn { padding: 8px 18px; background: #1a1a1a; color: white; border: none; border-radius: 4px;
                   font-size: 13px; cursor: pointer; }
  .dc-submit-btn:hover:not(:disabled) { background: #333; }
  .dc-submit-btn:disabled { background: #ccc; cursor: default; }
  .dc-done { font-size: 14px; color: #27ae60; padding: 6px 0; }
  .dc-done a { color: #27ae60; font-size: 13px; }
</style>
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Companion</h1>
    <div class="sub">{{ date_display }}</div>
  </div>

  {{ nav | safe }}

  {% if not brief %}
  <p class="empty">No brief available to respond to. <a href="/run">Run The Morning Loaf now →</a></p>
  {% else %}
  <p class="companion-intro">Respond to today's open questions. Your insights calibrate what Charlie surfaces next.</p>

  <div class="dc-toggle-row">
    <button id="dc-toggle-btn" class="dc-toggle-btn">Dark Comprandon: OFF</button>
    <span class="dc-toggle-hint">Adversary critique of today's brief</span>
  </div>

  {% set tier_defs = [
    ('tier_1', 'The Signal', brief.get('tier_1')),
    ('tier_2', 'The Bullshit Flag', brief.get('tier_2')),
    ('tier_3', 'Your World', brief.get('tier_3'))
  ] %}

  {% for tier_key, tier_label, tier in tier_defs %}
  <div class="tier-block">
    <div class="tier-label">{{ tier_label }}</div>
    {% if tier %}
    <div class="tier-headline">{{ tier.headline }}</div>
    {% if tier.open_question %}
    <div class="tier-question">→ {{ tier.open_question }}</div>
    {% endif %}

    <div class="field-group">
      <label class="field-label" for="insight-{{ tier_key }}">Your response</label>
      <textarea id="insight-{{ tier_key }}" placeholder="What does this tell you? What pattern does it fit or break?"></textarea>
    </div>

    <div class="field-group">
      <label class="field-label">This insight…</label>
      <div class="radio-group">
        <label><input type="radio" name="disposition-{{ tier_key }}" value="reinforces"> Reinforces the thesis</label>
        <label><input type="radio" name="disposition-{{ tier_key }}" value="challenges"> Challenges the thesis</label>
        <label><input type="radio" name="disposition-{{ tier_key }}" value="new_signal"> Surfaces something new</label>
        <label><input type="radio" name="disposition-{{ tier_key }}" value="tangential"> Tangential / not thesis-related</label>
      </div>
    </div>

    <div class="field-group">
      <label class="field-label" for="force-{{ tier_key }}">Thesis force</label>
      <select id="force-{{ tier_key }}">
        <option value="supply_exhaustion">Supply Exhaustion</option>
        <option value="demand_migration">Demand Migration</option>
        <option value="discovery_bridge">Discovery Bridge</option>
        <option value="general">General</option>
      </select>
    </div>

    <div class="field-group">
      <label class="field-label" for="category-{{ tier_key }}">Signal category</label>
      <span class="field-hint">Abstract label — e.g. "platform_exclusivity_strategy", "creator_brand_valuation"</span>
      <input type="text" id="category-{{ tier_key }}" placeholder="e.g. platform_exclusivity_strategy">
    </div>

    <div class="field-group">
      <label class="field-label">Confidence</label>
      <div class="confidence-row">
        <label><input type="radio" name="confidence-{{ tier_key }}" value="high"> High</label>
        <label><input type="radio" name="confidence-{{ tier_key }}" value="medium" checked> Medium</label>
        <label><input type="radio" name="confidence-{{ tier_key }}" value="low"> Low</label>
      </div>
    </div>

    <button class="submit-btn" data-question="{{ tier.open_question | default('') | e }}" onclick="submitTier('{{ tier_key }}', this.dataset.question, '{{ brief_date }}')">Submit</button>
    <div class="confirmation" id="confirm-{{ tier_key }}">Saved. Thank you.</div>
    <div class="error-msg" id="error-{{ tier_key }}">Something went wrong. Please try again.</div>

    {% else %}
    <p class="empty-tier">Nothing qualified today.</p>
    {% endif %}
  </div>
  {% endfor %}

  <div class="tier-block" style="border-top: 2px solid #1a1a1a; margin-top: 8px;">
    <div class="tier-label" style="margin-bottom: 12px;">Brain Dump</div>
    <p style="font-size: 14px; color: #666; margin-bottom: 20px; line-height: 1.6;">Anything on your mind that doesn't fit the tiers — patterns, hunches, things you're noticing. Write freely.</p>

    <div class="field-group">
      <textarea id="insight-freeform" rows="6" placeholder="What are you seeing? What keeps coming up?"></textarea>
    </div>

    <div class="field-group">
      <label class="field-label">This relates to the thesis by…</label>
      <div class="radio-group">
        <label><input type="radio" name="disposition-freeform" value="reinforces"> Reinforcing it</label>
        <label><input type="radio" name="disposition-freeform" value="challenges"> Challenging it</label>
        <label><input type="radio" name="disposition-freeform" value="new_signal"> Surfacing something new</label>
        <label><input type="radio" name="disposition-freeform" value="tangential"> Tangential / general observation</label>
      </div>
    </div>

    <div class="field-group">
      <label class="field-label" for="force-freeform">Thesis force</label>
      <select id="force-freeform">
        <option value="supply_exhaustion">Supply Exhaustion</option>
        <option value="demand_migration">Demand Migration</option>
        <option value="discovery_bridge">Discovery Bridge</option>
        <option value="general" selected>General</option>
      </select>
    </div>

    <div class="field-group">
      <label class="field-label">Confidence</label>
      <div class="confidence-row">
        <label><input type="radio" name="confidence-freeform" value="high"> High</label>
        <label><input type="radio" name="confidence-freeform" value="medium" checked> Medium</label>
        <label><input type="radio" name="confidence-freeform" value="low"> Low</label>
      </div>
    </div>

    <button class="submit-btn" onclick="submitFreeform('{{ brief_date }}')">Submit</button>
    <div class="confirmation" id="confirm-freeform">Saved. Thank you.</div>
    <div class="error-msg" id="error-freeform">Something went wrong. Please try again.</div>
  </div>

  <div id="dc-section" class="dc-wrap" style="display:none; margin-top: 40px;">
    <div class="dc-header-bar">
      <div class="dc-header-title">Dark Comprandon</div>
      {% if adversary and not adversary.null_finding %}
      <div class="dc-header-sub">Today's adversary found {{ adversary_total }} thing{{ 's' if adversary_total != 1 else '' }} worth pushing back on the brief about. Your responses are logged for Andrew to review. They do not feed back into Charlie's pipeline.</div>
      {% else %}
      <div class="dc-header-sub">No adversary output available for today's brief.</div>
      {% endif %}
    </div>
    <div class="dc-body">
      {% if not adversary or adversary.null_finding %}
      <p class="dc-null">The adversary found nothing to push back on today.</p>
      {% else %}
      {% if adversary.summary %}
      <p class="dc-summary">{{ adversary.summary }}</p>
      {% endif %}
      {% set dc_cats = [
        ('flattery', 'Flattery'),
        ('pattern_exhaustion', 'Pattern Exhaustion'),
        ('inference_theater', 'Inference Theater'),
        ('missing_story', 'Missing Story'),
        ('comfortable_framing', 'Comfortable Framing')
      ] %}
      {% for cat_key, cat_label in dc_cats %}
      {% set cat_items = adversary.findings.get(cat_key, []) %}
      <div class="dc-cat-header">{{ cat_label }}{% if cat_items %} ({{ cat_items|length }}){% endif %}</div>
      {% if not cat_items %}
      <p class="dc-no-findings">{{ cat_label }}: no findings today.</p>
      {% else %}
      {% for item in cat_items %}
      <div class="dc-card">
        <div class="dc-card-content">
          {% if cat_key == 'flattery' %}
          <div class="dc-citation">"{{ item.citation }}"</div>
          <div class="dc-item-meta">Tier: {{ item.tier }}{% if item.prior_session_id %} · Session: {{ item.prior_session_id }}{% endif %}</div>
          {% elif cat_key == 'pattern_exhaustion' %}
          <div class="dc-citation">{{ item.pattern }}</div>
          <div class="dc-item-meta">{{ item.occurrences }}× in {{ item.window_days }} days</div>
          {% elif cat_key == 'inference_theater' %}
          <div class="dc-citation">"{{ item.claim }}"</div>
          <div class="dc-item-meta">Signal: {{ item.underlying_signal }}</div>
          {% elif cat_key == 'missing_story' %}
          <div class="dc-citation">Signal: {{ item.signal_reference }}</div>
          <div class="dc-item-meta">Brief said: {{ item.declined_reading }}</div>
          {% elif cat_key == 'comfortable_framing' %}
          <div class="dc-citation">"{{ item.phrase }}"</div>
          <div class="dc-item-meta">Tier: {{ item.tier }}</div>
          {% endif %}
          <div class="dc-critique">{{ item.critique }}</div>
        </div>
        <div id="adv-done-{{ cat_key }}-{{ loop.index0 }}" class="dc-done" style="display:none"></div>
        <div id="adv-form-{{ cat_key }}-{{ loop.index0 }}">
          <div class="dc-radios">
            <label><input type="radio" name="adv-disp-{{ cat_key }}-{{ loop.index0 }}" value="fair_hit"> Fair hit</label>
            <label><input type="radio" name="adv-disp-{{ cat_key }}-{{ loop.index0 }}" value="off_base"> Off-base</label>
            <label><input type="radio" name="adv-disp-{{ cat_key }}-{{ loop.index0 }}" value="partially_right"> Partially right</label>
          </div>
          <textarea id="adv-note-{{ cat_key }}-{{ loop.index0 }}" class="dc-note" placeholder="Optional note..."></textarea>
          <button id="adv-btn-{{ cat_key }}-{{ loop.index0 }}" class="dc-submit-btn"
                  onclick="submitAdvFeedback('{{ cat_key }}', {{ loop.index0 }}, '{{ brief_date }}')">Submit</button>
        </div>
      </div>
      {% endfor %}
      {% endif %}
      {% endfor %}
      {% endif %}
    </div>
  </div>
  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>

<script>
function submitTier(tier, question, briefDate) {
  const insight = document.getElementById('insight-' + tier).value.trim();
  if (!insight) { alert('Please enter your response before submitting.'); return; }

  const dispositionEl = document.querySelector('input[name="disposition-' + tier + '"]:checked');
  if (!dispositionEl) { alert('Please select a disposition before submitting.'); return; }

  const force = document.getElementById('force-' + tier).value;
  const category = document.getElementById('category-' + tier).value.trim();
  const confidenceEl = document.querySelector('input[name="confidence-' + tier + '"]:checked');
  const confidence = confidenceEl ? confidenceEl.value : 'medium';

  const btn = document.querySelector('.tier-block .submit-btn[onclick*="' + tier + '"]');
  if (btn) btn.disabled = true;

  fetch('/api/companion/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      brief_date: briefDate,
      tier: tier,
      question: question,
      disposition: dispositionEl.value,
      thesis_force: force,
      signal_category: category,
      insight: insight,
      confidence: confidence,
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'ok') {
      document.getElementById('confirm-' + tier).style.display = 'block';
      document.getElementById('error-' + tier).style.display = 'none';
    } else {
      document.getElementById('error-' + tier).style.display = 'block';
      if (btn) btn.disabled = false;
    }
  })
  .catch(() => {
    document.getElementById('error-' + tier).style.display = 'block';
    if (btn) btn.disabled = false;
  });
}

// Dark Comprandon toggle
const DC_KEY = 'charlie_dc_on';
function lsGet(key) { try { return localStorage.getItem(key); } catch(e) { return null; } }
function lsSet(key, val) { try { localStorage.setItem(key, val); } catch(e) {} }
function initDC() {
  const on = lsGet(DC_KEY) === '1';
  const section = document.getElementById('dc-section');
  const btn = document.getElementById('dc-toggle-btn');
  if (section) section.style.display = on ? 'block' : 'none';
  if (btn) {
    btn.textContent = on ? 'Dark Comprandon: ON' : 'Dark Comprandon: OFF';
    btn.classList.toggle('dc-on', on);
  }
}
function toggleDC() {
  console.log('[DC] toggle fired, current:', lsGet(DC_KEY));
  const on = lsGet(DC_KEY) === '1';
  lsSet(DC_KEY, on ? '0' : '1');
  initDC();
}

async function submitAdvFeedback(category, findingIndex, adversaryDate) {
  const radioName = 'adv-disp-' + category + '-' + findingIndex;
  const dispositionEl = document.querySelector('input[name="' + radioName + '"]:checked');
  if (!dispositionEl) { alert('Select a response before submitting.'); return; }
  const noteEl = document.getElementById('adv-note-' + category + '-' + findingIndex);
  const note = noteEl ? noteEl.value.trim() : '';
  const btn = document.getElementById('adv-btn-' + category + '-' + findingIndex);
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch('/api/adversary/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adversary_date: adversaryDate, category: category,
                             finding_index: findingIndex, disposition: dispositionEl.value, note: note })
    });
    if (resp.ok) {
      const labels = { fair_hit: 'Fair hit', off_base: 'Off-base', partially_right: 'Partially right' };
      const dispLabel = labels[dispositionEl.value] || dispositionEl.value;
      const form = document.getElementById('adv-form-' + category + '-' + findingIndex);
      const done = document.getElementById('adv-done-' + category + '-' + findingIndex);
      if (form) form.style.display = 'none';
      if (done) {
        done.innerHTML = `Response recorded \u2014 <strong>${dispLabel}</strong>. <a href="#" onclick="reopenAdv('${category}',${findingIndex});return false;">Change</a>`;
        done.style.display = 'block';
      }
    } else {
      if (btn) btn.disabled = false;
      const errBody = await resp.json().catch(() => ({}));
      alert(errBody.error || 'Something went wrong. Please try again.');
    }
  } catch(e) {
    if (btn) btn.disabled = false;
    alert('Something went wrong. Please try again.');
  }
}

function reopenAdv(category, findingIndex) {
  const form = document.getElementById('adv-form-' + category + '-' + findingIndex);
  const done = document.getElementById('adv-done-' + category + '-' + findingIndex);
  const btn = document.getElementById('adv-btn-' + category + '-' + findingIndex);
  if (form) form.style.display = 'block';
  if (done) done.style.display = 'none';
  if (btn) btn.disabled = false;
}

document.addEventListener('DOMContentLoaded', function() {
  initDC();
  const btn = document.getElementById('dc-toggle-btn');
  if (btn) btn.addEventListener('click', toggleDC);
});

function submitFreeform(briefDate) {
  const insight = document.getElementById('insight-freeform').value.trim();
  if (!insight) { alert('Please enter something before submitting.'); return; }

  const dispositionEl = document.querySelector('input[name="disposition-freeform"]:checked');
  if (!dispositionEl) { alert('Please select a disposition before submitting.'); return; }

  const force = document.getElementById('force-freeform').value;
  const confidenceEl = document.querySelector('input[name="confidence-freeform"]:checked');
  const confidence = confidenceEl ? confidenceEl.value : 'medium';

  const btn = document.querySelector('.submit-btn[onclick*="submitFreeform"]');
  if (btn) btn.disabled = true;

  fetch('/api/companion/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      brief_date: briefDate,
      tier: 'freeform',
      question: null,
      disposition: dispositionEl.value,
      thesis_force: force,
      signal_category: '',
      insight: insight,
      confidence: confidence,
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'ok') {
      document.getElementById('confirm-freeform').style.display = 'block';
      document.getElementById('error-freeform').style.display = 'none';
    } else {
      document.getElementById('error-freeform').style.display = 'block';
      if (btn) btn.disabled = false;
    }
  })
  .catch(() => {
    document.getElementById('error-freeform').style.display = 'block';
    if (btn) btn.disabled = false;
  });
}
</script>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    _log.debug("request_received", route="/", method="GET")
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")], reverse=True)
    if available:
        return redirect(url_for("show_brief", brief_date=available[0]))
    return render_template_string(BRIEF_TEMPLATE, brief=None, signals=[],
                                 date_display="No briefs yet", nav=nav_html("brief"),
                                 current_date="", prev_date=None, next_date=None)


@app.route("/archive")
def archive():
    _log.debug("request_received", route="/archive", method="GET")
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


@app.route("/companion")
def companion():
    _log.debug("request_received", route="/companion", method="GET")
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")], reverse=True)

    brief = None
    brief_date = ""
    date_display = "No briefs yet"

    if available:
        brief_date = available[0]
        brief_path = briefs_dir / f"{brief_date}.json"
        try:
            with open(brief_path) as f:
                data = json.load(f)
                brief = data.get("brief", data)
        except (json.JSONDecodeError, KeyError):
            pass
        try:
            d = date.fromisoformat(brief_date)
            date_display = d.strftime("%A, %B %d, %Y")
        except ValueError:
            date_display = brief_date

    adversary = None
    adversary_total = 0
    if brief_date:
        try:
            adversary = state.load_adversary(date.fromisoformat(brief_date))
            if adversary and not adversary.get("null_finding", True):
                findings = adversary.get("findings", {})
                adversary_total = sum(len(v) for v in findings.values() if isinstance(v, list))
        except (ValueError, Exception):
            pass

    return render_template_string(COMPANION_TEMPLATE,
                                  brief=brief,
                                  brief_date=brief_date,
                                  date_display=date_display,
                                  nav=nav_html("companion"),
                                  adversary=adversary,
                                  adversary_total=adversary_total)


@app.route("/api/companion/session", methods=["POST"])
def submit_session():
    data = request.json
    _log.info("request_received", route="/api/companion/session", method="POST",
              tier=data.get("tier"), brief_date=data.get("brief_date"),
              disposition=data.get("disposition"))
    tier = data["tier"]
    date_str = data["brief_date"].replace("-", "")
    base_id = f"s_{date_str}_{tier}"

    # Ensure unique ID. Freeform entries always use a letter suffix (a, b, c…).
    # Tier entries use the base ID first, then _b, _c… on collision.
    existing = state.load_sessions(days_back=60)
    existing_ids = {s["id"] for s in existing}
    if tier == "freeform":
        suffix_ord = ord("a")
        entry_id = f"{base_id}_{chr(suffix_ord)}"
        while entry_id in existing_ids:
            suffix_ord += 1
            entry_id = f"{base_id}_{chr(suffix_ord)}"
    else:
        entry_id = base_id
        suffix_ord = ord("b")
        while entry_id in existing_ids:
            entry_id = f"{base_id}_{chr(suffix_ord)}"
            suffix_ord += 1

    entry = {
        "id": entry_id,
        "brief_date": data["brief_date"],
        "session_date": datetime.now().isoformat(),
        "tier": tier,
        "question": data.get("question", ""),
        "disposition": data["disposition"],
        "thesis_force": data["thesis_force"],
        "signal_category": data.get("signal_category", ""),
        "insight": data["insight"],
        "confidence": data.get("confidence", "medium"),
    }
    state.append_session(entry)
    _log.info("request_completed", route="/api/companion/session", method="POST", id=entry_id)
    return jsonify({"status": "ok", "id": entry_id})


_ADV_DISPOSITIONS = {"fair_hit", "off_base", "partially_right"}
_ADV_CATEGORIES = {"flattery", "pattern_exhaustion", "inference_theater", "missing_story", "comfortable_framing"}

@app.route("/api/adversary/feedback", methods=["POST"])
def submit_adversary_feedback():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    _log.info("request_received", route="/api/adversary/feedback", method="POST",
              category=data.get("category"), disposition=data.get("disposition"),
              adversary_date=data.get("adversary_date"))

    category = data.get("category", "")
    disposition = data.get("disposition", "")
    finding_index = data.get("finding_index")
    adversary_date_str = data.get("adversary_date", "")
    note = data.get("note") or ""

    if disposition not in _ADV_DISPOSITIONS:
        return jsonify({"error": "Invalid disposition"}), 400
    if category not in _ADV_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400
    try:
        adversary_date = date.fromisoformat(adversary_date_str)
    except ValueError:
        return jsonify({"error": "Invalid adversary_date"}), 400

    adversary = state.load_adversary(adversary_date)
    if not adversary:
        return jsonify({"error": "No adversary found for this date"}), 404

    cat_findings = adversary.get("findings", {}).get(category, [])
    if not isinstance(finding_index, int) or finding_index < 0 or finding_index >= len(cat_findings):
        return jsonify({"error": "Invalid finding_index"}), 400

    date_str = adversary_date_str.replace("-", "")
    entry = {
        "id": f"af_{date_str}_{category}_{finding_index}",
        "adversary_date": adversary_date_str,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "finding_index": finding_index,
        "disposition": disposition,
        "note": note,
    }
    state.save_adversary_feedback(entry)
    _log.info("request_completed", route="/api/adversary/feedback", method="POST", id=entry["id"])
    return jsonify(entry), 200


@app.route("/brief/<brief_date>")
def show_brief(brief_date):
    _log.debug("request_received", route="/brief/<brief_date>", method="GET", brief_date=brief_date)
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")])

    prev_date = None
    next_date = None
    if brief_date in available:
        idx = available.index(brief_date)
        if idx > 0:
            prev_date = available[idx - 1]
        if idx < len(available) - 1:
            next_date = available[idx + 1]

    brief_path = briefs_dir / f"{brief_date}.json"
    brief = None
    if brief_path.exists():
        with open(brief_path) as f:
            data = json.load(f)
            brief = data.get("brief", data)

    signals = []
    try:
        signals = state.load_signals(date.fromisoformat(brief_date))
    except ValueError:
        pass

    try:
        d = date.fromisoformat(brief_date)
        date_display = d.strftime("%A, %B %d, %Y")
    except ValueError:
        date_display = brief_date

    adversary = None
    try:
        adversary = state.load_adversary(date.fromisoformat(brief_date))
    except ValueError:
        pass

    return render_template_string(BRIEF_TEMPLATE,
                                 brief=brief, signals=signals,
                                 date_display=date_display,
                                 nav=nav_html("brief"),
                                 current_date=brief_date,
                                 prev_date=prev_date,
                                 next_date=next_date,
                                 adversary=adversary)


# ── Brief API ────────────────────────────────────────────────────────────

@app.route("/api/brief/<brief_date>")
def api_brief(brief_date):
    _log.debug("request_received", route="/api/brief/<brief_date>", method="GET", brief_date=brief_date)
    brief_path = config.briefs_dir / f"{brief_date}.json"
    if not brief_path.exists():
        return jsonify({"error": "Brief not found"}), 404
    with open(brief_path) as f:
        data = json.load(f)
    response = jsonify(data)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# ── Thesis Routes ────────────────────────────────────────────────────────

REVIEW_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Far Mar Review</title>
<style>
  """ + SHARED_STYLES + """
  .iteration-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
  .iteration-label { font-size: 13px; color: #666; }
  .iteration-dots { display: flex; gap: 6px; }
  .dot { font-size: 16px; color: #e0e0e0; }
  .dot.filled { color: #1a1a1a; }
  .summary-block { padding: 20px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; margin-bottom: 32px; }
  .summary-block p { font-size: 15px; color: #333; line-height: 1.6; }
  .section-label { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999; margin-bottom: 12px; margin-top: 32px; }
  .proposal-card { margin-bottom: 20px; padding: 20px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; }
  .item-id { font-size: 11px; color: #bbb; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .item-claim { font-size: 15px; color: #1a1a1a; line-height: 1.5; margin-bottom: 10px; }
  .item-original { font-size: 13px; color: #999; font-style: italic; margin-bottom: 6px; padding-left: 12px; border-left: 2px solid #e0e0e0; }
  .item-revised { font-size: 14px; color: #1a1a1a; margin-bottom: 10px; padding-left: 12px; border-left: 2px solid #3D5A80; }
  .item-meta { font-size: 12px; color: #999; margin-bottom: 6px; }
  .item-evidence { font-size: 12px; color: #aaa; margin-bottom: 14px; }
  .flag-row { display: flex; gap: 20px; margin-bottom: 12px; flex-wrap: wrap; }
  .flag-row label { font-size: 13px; color: #444; cursor: pointer; display: flex; align-items: center; gap: 6px; }
  .flag-row input[type="radio"] { accent-color: #3D5A80; }
  .annotation-field { width: 100%; padding: 8px 10px; border: 1px solid #e0e0e0; border-radius: 4px;
                      font-family: Georgia, serif; font-size: 14px; color: #1a1a1a; resize: vertical;
                      min-height: 60px; margin-top: 4px; }
  .annotation-field:focus { outline: none; border-color: #3D5A80; }
  .action-bar { display: flex; align-items: center; justify-content: space-between; margin-top: 40px;
                padding: 20px 0; border-top: 2px solid #e0e0e0; }
  .action-right { display: flex; gap: 12px; }
  .btn-refine { background: #1a1a1a; color: white; padding: 10px 22px; border: none; border-radius: 4px;
                font-size: 14px; cursor: pointer; font-family: Georgia, serif; }
  .btn-refine:hover:not(:disabled) { background: #333; }
  .btn-refine:disabled { background: #ccc; cursor: default; color: #999; }
  .btn-discard { background: white; color: #c0392b; border: 1px solid #c0392b; padding: 10px 20px;
                 border-radius: 4px; font-size: 14px; cursor: pointer; font-family: Georgia, serif; }
  .btn-discard:hover { background: #fde8e8; }
  .btn-publish { background: #27ae60; color: white; border: none; padding: 10px 22px;
                 border-radius: 4px; font-size: 14px; cursor: pointer; font-family: Georgia, serif; }
  .btn-publish:hover { background: #1e8449; }
  .loading-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                     background: rgba(255,255,255,0.92); z-index: 100;
                     align-items: center; justify-content: center; flex-direction: column; }
  .loading-msg { font-size: 17px; color: #1a1a1a; text-align: center; line-height: 2; }
  .status-published { padding: 16px 20px; background: #d5f5e3; color: #1a7a45; border-radius: 6px;
                      font-size: 14px; margin-bottom: 24px; }
  .status-discarded { padding: 16px 20px; background: #f5f5f5; color: #999; border-radius: 6px;
                      font-size: 14px; margin-bottom: 24px; }
</style>
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Far Mar Review</h1>
    <div class="sub">{{ proposal_date_display }}</div>
  </div>

  {{ nav | safe }}

  {% if not proposal %}
  <p class="empty">No proposal available. Far Mar runs on Saturday mornings.</p>

  {% elif proposal.status == 'published' %}
  <div class="status-published">This proposal has been published. <a href="/thesis">View Far Mar →</a></div>

  {% elif proposal.status == 'discarded' %}
  <div class="status-discarded">This proposal was discarded.</div>

  {% else %}

  <div class="iteration-row">
    <span class="iteration-label">Iteration {{ proposal.iteration }} of {{ proposal.max_iterations }}</span>
    <span class="iteration-dots">
      {% for i in range(proposal.max_iterations) %}
      <span class="dot {{ 'filled' if i < proposal.iteration else '' }}">●</span>
      {% endfor %}
    </span>
  </div>

  {% if proposal.summary %}
  <div class="summary-block">
    <p>{{ proposal.summary }}</p>
  </div>
  {% endif %}

  {% if proposal.extensions %}
  <div class="section-label">Proposed Extensions</div>
  {% for item in proposal.extensions %}
  <div class="proposal-card" data-id="{{ item.id }}" data-section="extensions">
    <div class="item-id">{{ item.id }}</div>
    <div class="item-claim">{{ item.claim }}</div>
    <div class="item-meta">Force: {{ item.get('force', '—') }} · Confidence: {{ item.get('confidence', '—') }}</div>
    {% if item.evidence %}
    <div class="item-evidence">Evidence: {{ item.evidence | join(', ') }}</div>
    {% endif %}
    <div class="flag-row">
      <label><input type="radio" name="flag-{{ item.id }}" value="accept" {{ 'checked' if item.flag == 'accept' }}> Accept</label>
      <label><input type="radio" name="flag-{{ item.id }}" value="needs_revision" {{ 'checked' if item.flag == 'needs_revision' }}> Needs revision</label>
      <label><input type="radio" name="flag-{{ item.id }}" value="reject" {{ 'checked' if item.flag == 'reject' }}> Reject</label>
    </div>
    <textarea class="annotation-field" placeholder="Your response…">{{ item.annotation or '' }}</textarea>
  </div>
  {% endfor %}
  {% endif %}

  {% if proposal.revisions %}
  <div class="section-label">Proposed Revisions</div>
  {% for item in proposal.revisions %}
  <div class="proposal-card" data-id="{{ item.id }}" data-section="revisions">
    <div class="item-id">{{ item.id }}</div>
    {% if item.get('original_claim') %}
    <div class="item-original">Currently: {{ item.original_claim }}</div>
    {% endif %}
    <div class="item-revised">Proposed: {{ item.get('revised_claim', item.get('claim', '')) }}</div>
    {% if item.get('rationale') %}
    <div class="item-meta">{{ item.rationale }}</div>
    {% endif %}
    {% if item.evidence %}
    <div class="item-evidence">Evidence: {{ item.evidence | join(', ') }}</div>
    {% endif %}
    <div class="flag-row">
      <label><input type="radio" name="flag-{{ item.id }}" value="accept" {{ 'checked' if item.flag == 'accept' }}> Accept</label>
      <label><input type="radio" name="flag-{{ item.id }}" value="needs_revision" {{ 'checked' if item.flag == 'needs_revision' }}> Needs revision</label>
      <label><input type="radio" name="flag-{{ item.id }}" value="reject" {{ 'checked' if item.flag == 'reject' }}> Reject</label>
    </div>
    <textarea class="annotation-field" placeholder="Your response…">{{ item.annotation or '' }}</textarea>
  </div>
  {% endfor %}
  {% endif %}

  {% if proposal.new_patterns %}
  <div class="section-label">New Patterns</div>
  {% for item in proposal.new_patterns %}
  <div class="proposal-card" data-id="{{ item.id }}" data-section="new_patterns">
    <div class="item-id">{{ item.id }}</div>
    <div class="item-claim">{{ item.pattern }}</div>
    <div class="item-meta">Suggested force: {{ item.get('suggested_force', '—') }}</div>
    {% if item.evidence %}
    <div class="item-evidence">Evidence: {{ item.evidence | join(', ') }}</div>
    {% endif %}
    <div class="flag-row">
      <label><input type="radio" name="flag-{{ item.id }}" value="accept" {{ 'checked' if item.flag == 'accept' }}> Accept</label>
      <label><input type="radio" name="flag-{{ item.id }}" value="needs_revision" {{ 'checked' if item.flag == 'needs_revision' }}> Needs revision</label>
      <label><input type="radio" name="flag-{{ item.id }}" value="reject" {{ 'checked' if item.flag == 'reject' }}> Reject</label>
    </div>
    <textarea class="annotation-field" placeholder="Your response…">{{ item.annotation or '' }}</textarea>
  </div>
  {% endfor %}
  {% endif %}

  <div class="action-bar">
    <button class="btn-refine" onclick="triggerRefine()"
      {% if proposal.iteration >= proposal.max_iterations %}disabled title="Maximum refinements reached"{% endif %}>
      {% if proposal.iteration >= proposal.max_iterations %}Maximum refinements reached{% else %}Refine ↻{% endif %}
    </button>
    <div class="action-right">
      <button class="btn-discard" onclick="triggerDiscard()">Discard ✗</button>
      <button class="btn-publish" onclick="triggerPublish()">Publish ✓</button>
    </div>
  </div>

  <div class="loading-overlay" id="loading-overlay">
    <div class="loading-msg">Refining with Opus…<br><span style="font-size:13px;color:#666;">This takes 30–60 seconds.</span></div>
  </div>

  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>

<script>
function collectAnnotations() {
  const cards = document.querySelectorAll('.proposal-card');
  const annotations = [];
  cards.forEach(card => {
    const id = card.dataset.id;
    const section = card.dataset.section;
    const flagEl = card.querySelector(`input[name="flag-${id}"]:checked`);
    const annotationEl = card.querySelector('.annotation-field');
    annotations.push({
      id: id,
      section: section,
      flag: flagEl ? flagEl.value : null,
      annotation: annotationEl ? annotationEl.value.trim() : '',
    });
  });
  return annotations;
}

async function saveAnnotations() {
  const annotations = collectAnnotations();
  await fetch('/api/thesis/annotate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({annotations}),
  });
}

async function triggerRefine() {
  await saveAnnotations();
  document.getElementById('loading-overlay').style.display = 'flex';
  try {
    const resp = await fetch('/api/thesis/refine', {method: 'POST'});
    const data = await resp.json();
    if (data.status === 'ok') {
      location.reload();
    } else {
      document.getElementById('loading-overlay').style.display = 'none';
      alert('Refinement failed: ' + (data.message || 'Unknown error'));
    }
  } catch(e) {
    document.getElementById('loading-overlay').style.display = 'none';
    alert('Refinement failed. Please try again.');
  }
}

async function triggerPublish() {
  if (!confirm('This will update Far Mar. The next Morning Loaf will run against the updated Far Mar. Publish?')) return;
  await saveAnnotations();
  const resp = await fetch('/api/thesis/publish', {method: 'POST'});
  const data = await resp.json();
  if (data.status === 'ok') {
    window.location.href = '/thesis';
  } else {
    alert('Publish failed: ' + (data.message || 'Unknown error'));
  }
}

async function triggerDiscard() {
  if (!confirm('Discard this proposal without applying it?')) return;
  const resp = await fetch('/api/thesis/discard', {method: 'POST'});
  const data = await resp.json();
  if (data.status === 'ok') {
    window.location.href = '/thesis';
  } else {
    alert('Discard failed: ' + (data.message || 'Unknown error'));
  }
}
</script>
</body>
</html>"""


THESIS_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Far Mar</title>
<style>
  """ + SHARED_STYLES + """
  .pending-notice { font-size: 13px; color: #7a5c00; background: #fffbe6; border: 1px solid #f5e04a;
                    padding: 10px 16px; border-radius: 4px; margin-bottom: 24px; }
  .pending-notice a { color: #7a5c00; font-weight: bold; }
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
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Far Mar</h1>
    <div class="sub">Entertainment Industry Restructuring</div>
  </div>

  {{ nav | safe }}

  {% if pending_proposal_date %}
  <div class="pending-notice">A proposal from {{ pending_proposal_date }} is awaiting review. <a href="/thesis/review">→ Review it</a></div>
  {% endif %}

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
<title>Charlie — The Field</title>
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

  /* Field Work section */
  .field-section { margin-top: 48px; border-top: 2px solid #e0e0e0; padding-top: 28px; }
  .field-section h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 20px; }
  .upload-area { background: #f9f9f9; border: 2px dashed #ccc; border-radius: 8px; padding: 28px 24px; margin-bottom: 28px; }
  .upload-field { margin-bottom: 12px; }
  .upload-field label { display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 5px; }
  .upload-field input[type=file] { font-size: 13px; width: 100%; }
  .upload-field input[type=text], .upload-field select, .upload-field textarea { width: 100%; padding: 8px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; font-family: inherit; box-sizing: border-box; }
  .upload-field textarea { resize: vertical; min-height: 60px; }
  .upload-field select { background: white; }
  .upload-submit-row { display: flex; gap: 12px; align-items: center; margin-top: 16px; }
  .upload-submit-row button { padding: 9px 22px; background: #3D5A80; color: white; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
  .upload-submit-row button:hover { background: #2e4565; }
  .upload-submit-row button:disabled { background: #999; cursor: default; }
  #upload-error { font-size: 13px; color: #c0392b; }
  .artifact-list { }
  .artifact-item-wrapper { position: relative; margin-bottom: 8px; }
  .artifact-item { display: block; padding: 14px 16px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; text-decoration: none; color: inherit; }
  .artifact-item:hover { border-color: #3D5A80; }
  .artifact-name { font-size: 14px; font-weight: 600; color: #1a1a1a; }
  .artifact-meta { font-size: 12px; color: #999; margin-top: 4px; }
  .artifact-delete-btn { position: absolute; top: 11px; right: 10px; background: none; border: none; cursor: pointer; font-size: 13px; color: #ccc; padding: 2px 6px; border-radius: 3px; line-height: 1; font-family: inherit; }
  .artifact-delete-btn:hover { color: #888; background: #f5f5f5; }
  .artifact-tag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-right: 6px; }
  .tag-type { background: #e8f0fb; color: #3D5A80; }
  .tag-complete { background: #d5f5e3; color: #27ae60; }
  .tag-pending { background: #f2f3f4; color: #999; }
  .tag-failed { background: #fde8e8; color: #c0392b; }
  .tag-generating { background: #fef9e7; color: #b7950b; }
</style>
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Field</h1>
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

  <div class="field-section">
    <h3>Field Work</h3>

    <div class="upload-area">
      <div class="upload-field">
        <label>File <span style="color:#c0392b">*</span></label>
        <input type="file" id="fw-file" accept=".docx,.xlsx,.pdf,.pptx,.md,.txt">
      </div>
      <div class="upload-field">
        <label>Title <span style="color:#c0392b">*</span></label>
        <input type="text" id="fw-title" placeholder="Document title">
      </div>
      <div class="upload-field">
        <label>Type <span style="color:#c0392b">*</span></label>
        <select id="fw-type">
          <option value="">— select —</option>
          <option value="research">Research</option>
          <option value="memo">Memo</option>
          <option value="notes">Notes</option>
          <option value="reference">Reference</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div class="upload-field">
        <label>Description</label>
        <textarea id="fw-desc" placeholder="Optional context or notes about this document"></textarea>
      </div>
      <div class="upload-submit-row">
        <button id="fw-submit" onclick="uploadFieldWork()">Upload</button>
        <span id="upload-error"></span>
      </div>
    </div>

    <div class="artifact-list">
      {% if artifacts %}
      {% for a in artifacts %}
      <div class="artifact-item-wrapper">
        <a class="artifact-item" href="/field/work/{{ a.id }}">
          <div class="artifact-name">{{ a.title or a.filename }}</div>
          <div class="artifact-meta">
            <span class="artifact-tag tag-type">{{ a.type or 'other' }}</span>
            <span class="artifact-tag {% if a.extraction_status == 'complete' %}tag-complete{% elif a.extraction_status == 'failed' %}tag-failed{% else %}tag-pending{% endif %}">
              {{ a.extraction_status or 'pending' }}
            </span>
            {% if a.acknowledgment_status == 'complete' %}<span class="artifact-tag tag-complete">&#10003; First read</span>
            {% elif a.acknowledgment_status == 'generating' %}<span class="artifact-tag tag-generating">Charlie is reading&#8230;</span>
            {% elif a.acknowledgment_status == 'failed' %}<span class="artifact-tag tag-failed">Read failed</span>
            {% endif %}{{ a.format | upper if a.format else '' }} &middot; {{ a.word_count or '—' }} words &middot; {{ a.uploaded_at[:10] if a.uploaded_at else '' }}
          </div>
        </a>
        <button class="artifact-delete-btn" data-id="{{ a.id }}" data-title="{{ (a.title or a.filename) | e }}" onclick="deleteFieldArtifact(this.dataset.id, this.dataset.title, this)" title="Delete">&#215;</button>
      </div>
      {% endfor %}
      {% else %}
      <p class="empty">No Field Work uploaded yet.</p>
      {% endif %}
    </div>
  </div>

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
<script>
// Auto-fill title from filename on file selection
document.getElementById('fw-file').addEventListener('change', function() {
  var file = this.files[0];
  if (!file) return;
  var titleInput = document.getElementById('fw-title');
  if (!titleInput.value) {
    var name = file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
    titleInput.value = name;
  }
});

function uploadFieldWork() {
  var fileInput  = document.getElementById('fw-file');
  var titleInput = document.getElementById('fw-title');
  var typeSelect = document.getElementById('fw-type');
  var descInput  = document.getElementById('fw-desc');
  var btn        = document.getElementById('fw-submit');
  var errEl      = document.getElementById('upload-error');

  errEl.textContent = '';

  var file = fileInput.files[0];
  if (!file)                   { errEl.textContent = 'Select a file.'; return; }
  if (!titleInput.value.trim()) { errEl.textContent = 'Title is required.'; return; }
  if (!typeSelect.value)        { errEl.textContent = 'Select a type.'; return; }

  btn.disabled = true;
  btn.textContent = 'Uploading\u2026';

  var formData = new FormData();
  formData.append('file',        file);
  formData.append('title',       titleInput.value.trim());
  formData.append('type',        typeSelect.value);
  formData.append('description', descInput.value.trim());

  fetch('/api/field/upload', { method: 'POST', body: formData })
    .then(function(r) {
      btn.textContent = 'Processing\u2026';
      return r.json();
    })
    .then(function(data) {
      if (data.status === 'ok') {
        window.location.href = '/field/work/' + data.id;
      } else {
        errEl.textContent = data.message || 'Upload failed.';
        btn.disabled = false;
        btn.textContent = 'Upload';
      }
    })
    .catch(function(err) {
      errEl.textContent = 'Upload failed: ' + err.message;
      btn.disabled = false;
      btn.textContent = 'Upload';
      if (window.reportClientError) window.reportClientError('field upload failed', { error: String(err) });
    });
}

function deleteFieldArtifact(id, title, btn) {
  if (!confirm('Delete "' + title + '"? This cannot be undone.')) return;
  var wrapper = btn.closest('.artifact-item-wrapper');
  btn.disabled = true;
  fetch('/api/field/' + id, { method: 'DELETE' })
    .then(function(r) {
      if (!r.ok) throw new Error('Delete failed (' + r.status + ')');
      wrapper.remove();
    })
    .catch(function(err) {
      btn.disabled = false;
      var existing = wrapper.querySelector('.delete-error');
      if (existing) existing.remove();
      var errEl = document.createElement('span');
      errEl.className = 'delete-error';
      errEl.textContent = ' Delete failed.';
      errEl.style.cssText = 'font-size:11px;color:#c00;margin-left:6px;';
      wrapper.querySelector('.artifact-meta').appendChild(errEl);
    });
}
</script>
</body>
</html>"""


@app.route("/thesis")
def show_thesis():
    _log.debug("request_received", route="/thesis", method="GET")
    thesis = state.load_thesis()
    if not thesis:
        _ensure_thesis_seed()
        thesis = state.load_thesis()

    proposal, _ = state.load_latest_proposal()
    pending_proposal_date = None
    if proposal and proposal.get("status") not in ("published", "discarded"):
        try:
            d = date.fromisoformat(proposal.get("generated_at", "")[:10])
            pending_proposal_date = d.strftime("%B %d, %Y")
        except (ValueError, AttributeError):
            pending_proposal_date = "this week"

    return render_template_string(THESIS_TEMPLATE, thesis=thesis, nav=nav_html("thesis"),
                                  pending_proposal_date=pending_proposal_date)


@app.route("/thesis/review")
def thesis_review():
    _log.debug("request_received", route="/thesis/review", method="GET")
    proposal, _ = state.load_latest_proposal()
    proposal_date_display = "No proposal"
    if proposal:
        try:
            d = date.fromisoformat(proposal.get("generated_at", "")[:10])
            proposal_date_display = d.strftime("%B %d, %Y")
        except (ValueError, AttributeError):
            proposal_date_display = "Recent proposal"
    return render_template_string(REVIEW_TEMPLATE, proposal=proposal,
                                  proposal_date_display=proposal_date_display,
                                  nav=nav_html("thesis"))


@app.route("/api/thesis/annotate", methods=["POST"])
def annotate_proposal():
    _log.info("request_received", route="/api/thesis/annotate", method="POST")
    proposal, path = state.load_latest_proposal()
    if not proposal or not path:
        return jsonify({"status": "error", "message": "No proposal found"}), 404
    annotations = request.json.get("annotations", [])
    for ann in annotations:
        item_id = ann["id"]
        section = ann["section"]
        for item in proposal.get(section, []):
            if item["id"] == item_id:
                item["flag"] = ann.get("flag")
                item["annotation"] = ann.get("annotation")
                break
    state.save_proposal_update(proposal, path)
    _log.info("request_completed", route="/api/thesis/annotate", method="POST", annotation_count=len(annotations))
    return jsonify({"status": "ok"})


@app.route("/api/thesis/refine", methods=["POST"])
def refine_thesis():
    _log.info("request_received", route="/api/thesis/refine", method="POST")
    proposal, path = state.load_latest_proposal()
    if not proposal or not path:
        return jsonify({"status": "error", "message": "No proposal found"}), 404
    if proposal.get("iteration", 0) >= proposal.get("max_iterations", 5):
        return jsonify({"status": "error", "message": "Maximum iterations reached"}), 400
    thesis = state.load_thesis()
    from agents.thesis import refine_proposal
    revised = refine_proposal(proposal, thesis)
    state.save_proposal_update(revised, path)
    _log.info("request_completed", route="/api/thesis/refine", method="POST", iteration=revised["iteration"])
    return jsonify({"status": "ok", "iteration": revised["iteration"]})


@app.route("/api/thesis/publish", methods=["POST"])
def publish_thesis():
    _log.info("request_received", route="/api/thesis/publish", method="POST")
    proposal, path = state.load_latest_proposal()
    if not proposal or not path:
        return jsonify({"status": "error", "message": "No proposal found"}), 404
    from agents.thesis import publish_proposal
    success = publish_proposal(proposal)
    if success:
        proposal["status"] = "published"
        state.save_proposal_update(proposal, path)
        _log.info("request_completed", route="/api/thesis/publish", method="POST")
        return jsonify({"status": "ok"})
    _log.error("request_failed", route="/api/thesis/publish", method="POST", reason="publish_failed")
    return jsonify({"status": "error", "message": "Publish failed"}), 500


@app.route("/api/thesis/discard", methods=["POST"])
def discard_proposal():
    _log.info("request_received", route="/api/thesis/discard", method="POST")
    proposal, path = state.load_latest_proposal()
    if not proposal or not path:
        return jsonify({"status": "error", "message": "No proposal found"}), 404
    proposal["status"] = "discarded"
    state.save_proposal_update(proposal, path)
    _log.info("request_completed", route="/api/thesis/discard", method="POST")
    return jsonify({"status": "ok"})


@app.route("/book")
def redirect_book():
    return redirect(url_for("show_field"), code=301)


@app.route("/field")
def show_field():
    _log.debug("request_received", route="/field", method="GET")
    thesis = state.load_thesis()
    if not thesis:
        _ensure_thesis_seed()
        thesis = state.load_thesis()
    artifacts = state.list_field_artifacts()
    _log.info("request_completed", route="/field", method="GET", artifacts=len(artifacts))
    return render_template_string(BOOK_TEMPLATE, thesis=thesis, nav=nav_html("field"), artifacts=artifacts)


def _ensure_thesis_seed():
    path = config.data_dir / "thesis" / "current.json"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = {"core_argument":"Hollywood's century-old system for finding and developing intellectual property is breaking down. The traditional pipeline — books, comics, spec scripts, licensing — was built for an era of scarcity, when a handful of broadcast slots and theatrical windows could sustain premium pricing on every title. Streaming destroyed that scarcity, demanding volume the old pipeline cannot produce. Simultaneously, the audiences studios need have migrated to platforms with fundamentally better content discovery — YouTube, TikTok, podcasting — pulled not by superior content but by superior matching. The only proven mechanism for reaching those audiences in scripted formats is through the creator brands they already trust. This is not a trend. It is a structural reorganization of how entertainment finds its way to people, and the executives and companies who understand it hold an asymmetric advantage.","updated_at":"2026-03-29T18:00:00","version":1,"forces":{"supply_exhaustion":{"summary":"The traditional IP pipeline was designed to feed a scarcity-based system. Streaming inverted this — platforms need hundreds of titles per year, not dozens. The pipeline built for scarcity cannot produce at volume, and the economics show it: option prices are inflating, conversion rates are declining, and entire categories show signs of exhaustion.","evidence":["Netflix walked away from acquiring WBD's full library — DC, Harry Potter, HBO catalog — for $82.7B. Its stock rose. The market priced legacy IP as a harvest asset, not a growth asset.","Paramount-WBD $111B merger is 85% dependent on linear cable profits — defensive consolidation, not growth investment.","Video game adaptation pipeline reached historic density in 2026 with six theatrical releases, suggesting rapid mining of a previously untapped category.","Sony Pictures Television folded its nonfiction division under scripted leadership, issued buyouts, saw senior departures — structural contraction in traditional development.","Romantasy publishing hit $600M in sales in 2024 but Hollywood has failed to convert a single major adaptation — widening gap between publishing success and screen conversion."],"confidence":"high","gaps":["No systematic longitudinal data on book option price inflation","Conversion rate from option to production across IP categories over time","Song/jukebox model depth unclear beyond Bohemian Rhapsody and Rocketman","Board game/toy IP after Barbie — no second proof point"]},"demand_migration":{"summary":"Audiences aren't choosing creator content over scripted — they're being captured by platforms with radically better discovery. YouTube, TikTok, and Spotify match individuals to content with precision no streamer replicates. The migration is a discovery problem, not a content preference problem.","evidence":["YouTube commands 11.1% of all TV streaming in the U.S., surpassing Netflix at 8.5%.","Streaming hit 47.5% of total TV viewing in December 2025, but Gen Z daily TV viewing at 36% vs. 73% for Boomers.","YouTube has 1 billion monthly active podcast viewers, 700M hours of living room podcast viewing in October 2025.","72% of podcast listeners prefer shows with video (Cumulus Media).","U.S. ad spending on creators projected at $37B in 2025, up from $13.9B four years prior — 4x broader media growth rate."],"confidence":"high","gaps":["No direct measurement of the algorithmic discovery gap between creator platforms and streamers","Demo-specific migration patterns not tracked longitudinally","Whether creator-branded shows have different retention curves — no platform publishes this","Whether any streamer uses creator audience data to improve recommendations"]},"discovery_bridge":{"summary":"Creator-branded content is the only proven mechanism for reaching algorithmically-sorted audiences in scripted formats. The creator brand functions as targeting infrastructure — more precise than ad campaigns and free to the platform.","evidence":["Netflix committed to 50-75 original video podcast shows for 2026, competing with YouTube for casual viewing at $5K-50K per episode vs. $3-10M for scripted.","Netflix pulled Ringer content off YouTube, locked iHeartMedia into exclusivity — treating creator audiences as proprietary acquisition channels.","Wondery's systematic pipeline: Dirty John, Dr. Death, Shrink Next Door, WeCrashed, Joe vs. Carole.","Audiochuck $250M valuation, Chernin investment, Matt Shanfield hired from Sony to build TV/film division.","57% of new streaming subscribers choosing ad-supported tiers, creating volume demand creator content fills.","Golden Globes introduced first podcast category in 2026."],"confidence":"medium-high","gaps":["No study directly measuring podcast-to-TV audience conversion rates","How development execs at creator-native companies protect brand differently","Economics of creator-driven audience acquisition vs. traditional marketing spend","Whether proof-of-concept model actually reduces production failure rates"]}},"ip_landscape":{"traditional":{"books":{"status":"saturating","notes":"Option prices inflating. Romantasy ($600M sales) failing to convert to screen."},"comics":{"status":"fatigued","notes":"Marvel/DC tentpole fatigue. Independent comics/manga undertapped."},"video_games":{"status":"accelerating","notes":"Six theatrical releases 2026. Last of Us, Fallout, Mario proved it. A24/Garland on Elden Ring."},"songs_jukebox":{"status":"early","notes":"Bohemian Rhapsody ($910M), Rocketman proved model. Piña Colada in development. Vast untapped catalog."},"theater":{"status":"stable","notes":"Hamilton model works but narrow pipeline. Not a volume solution."},"journalism":{"status":"evolved","notes":"Magazine-to-film pipeline absorbed into podcast-driven true crime."},"life_rights":{"status":"heavily_mined","notes":"Podcast layer gives new packaging but same underlying material. True crime fatigue risk."},"board_games_toys":{"status":"uncertain","notes":"Barbie ($1.4B) proved model but no second proof point. Mattel slate unproven."}},"creator_driven":{"podcasts":{"status":"most_mature","notes":"Systematic pipelines at Wondery, Audiochuck, Spotify Studios. Netflix entering with 50-75 shows."},"youtube":{"status":"accelerating","notes":"MrBeast/Netflix model. 11.1% TV streaming. YouTube securing NFL and Oscars (2029)."},"tiktok":{"status":"nascent","notes":"Talent discovery engine but U.S. regulatory uncertainty limits investment."},"newsletters":{"status":"early","notes":"The Optionist, Free Press/Paramount, Fox/Meet Cute. Small but high-value."},"livestreaming":{"status":"emerging","notes":"Markiplier Iron Lung in theaters 2026. A24/Backrooms. Kai Cenat/Kevin Hart film."}}},"development_function":{"summary":"Nobody is writing about what happens inside the companies building the bridge — what the development executive's job looks like when IP originates from a creator ecosystem. This is the thesis's most original territory.","key_questions":["How does the development role at Audiochuck differ from the same role at a traditional studio?","When the creator IS the brand, how do you protect IP without constraining the relationship that makes it valuable?","How should creator-driven IP be valued when the asset is audience relationship depth?","What creative control structures work when a bad adaptation damages the entire company?","Where do the bridging executives come from and what does their career path look like?"],"tracked_executives":[{"name":"Aaron Hart","company":"Wondery","title":"Head of TV and Film","track_record":"Dirty John, Dr. Death, Shrink Next Door, WeCrashed, Joe vs. Carole"},{"name":"Matt Shanfield","company":"Audiochuck","title":"Head of TV/Film Division","background":"Sony Pictures Television Nonfiction president"},{"name":"Jordan Moblo","company":"Universal Studio Group","title":"EVP Creative Acquisitions & IP Management"},{"name":"Marshall Lewy","company":"Wondery","title":"Chief Content Officer"}]},"claims":[{"id":1,"claim":"The restructuring is driven by three converging forces — supply exhaustion, demand migration, and the discovery bridge. Their interaction makes the shift structural, not cyclical.","confidence":"high","force":"all"},{"id":2,"claim":"Creator-branded content functions as audience targeting infrastructure. The value is the pre-sorted audience, not the IP.","confidence":"medium-high","force":"discovery_bridge"},{"id":3,"claim":"The development function at creator-native companies is fundamentally different from traditional studios, and building it well is the binding constraint on success.","confidence":"medium","force":"discovery_bridge"},{"id":4,"claim":"Traditional IP pipelines are declining unevenly — games and songs accelerating, books and comics saturating — but total volume is insufficient regardless.","confidence":"medium-high","force":"supply_exhaustion"},{"id":5,"claim":"Audience migration is driven by superior algorithmic discovery, not content quality decline. The solution is better discovery, not better content.","confidence":"medium","force":"demand_migration"}],"evidence":[],"book_project":{"status":"advance_offers_received","working_title":"TBD","narrative_arc":"The book tells the story of an industry losing its audience — not because it forgot how to make great content, but because the infrastructure that connected content to audiences broke, and a new one is being built by people Hollywood doesn't yet recognize as peers.","chapter_outline":[{"chapter":1,"title":"The Pipeline That Built Hollywood","focus":"The century-old system for finding stories. Why scarcity made every bet defensible.","status":"lit_review_complete"},{"chapter":2,"title":"The Exhaustion","focus":"What happens when a scarcity-based pipeline meets streaming-era volume demand.","status":"research_in_progress"},{"chapter":3,"title":"The Great Migration","focus":"Where the audience went and why. The algorithmic discovery gap as root cause.","status":"research_in_progress"},{"chapter":4,"title":"The YouTube Precedent","focus":"Fifteen years of creator ecosystem data. MCN boom and bust. What survived.","status":"lit_review_complete"},{"chapter":5,"title":"The Audio Bridge","focus":"Podcasting as the most mature creator-to-scripted pipeline. Wondery, Audiochuck, Netflix.","status":"research_in_progress"},{"chapter":6,"title":"The New Development Executive","focus":"The job nobody has defined yet. Case studies from Wondery, Audiochuck, UCP Audio.","status":"not_started"},{"chapter":7,"title":"The Discovery Problem","focus":"Why streamers can't find audiences. Creator brands as targeting infrastructure.","status":"research_in_progress"},{"chapter":8,"title":"What Comes Next","focus":"Video games, music catalogs, newsletters, livestreaming. The next wave.","status":"not_started"}]}}
    with open(path, "w") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)
    print(f"[Seed] Wrote thesis seed to {path}")


# ── Field Work Templates & Routes ────────────────────────────────────────────

FIELD_WORK_DETAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — {{ artifact.title or artifact.filename }}</title>
<style>
  """ + SHARED_STYLES + """
  .back-link { font-size: 13px; color: #3D5A80; text-decoration: none; display: inline-block; margin-bottom: 20px; }
  .back-link:hover { text-decoration: underline; }
  .artifact-header { margin-bottom: 28px; }
  .artifact-header h2 { font-size: 22px; margin-bottom: 8px; }
  .artifact-meta-row { font-size: 13px; color: #999; margin-bottom: 6px; }
  .artifact-tag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-right: 6px; }
  .tag-type { background: #e8f0fb; color: #3D5A80; }
  .tag-complete { background: #d5f5e3; color: #27ae60; }
  .tag-pending { background: #f2f3f4; color: #999; }
  .tag-failed { background: #fde8e8; color: #c0392b; }
  .tag-generating { background: #fef9e7; color: #b7950b; }
  .artifact-description { font-size: 14px; color: #555; margin-top: 8px; font-style: italic; }
  .download-link { display: inline-block; margin-top: 10px; font-size: 13px; color: #3D5A80; text-decoration: none; }
  .download-link:hover { text-decoration: underline; }

  .extracted-header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 16px; border-top: 2px solid #e0e0e0; padding-top: 24px; margin-top: 32px; }
  .extracted-header h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin: 0; }
  .word-count { font-size: 13px; color: #bbb; }

  .notes-block { background: #fef9e7; border: 1px solid #f0d080; border-radius: 6px; padding: 12px 16px; margin-bottom: 16px; font-size: 13px; color: #7a6000; }
  .notes-block ul { margin: 6px 0 0 18px; padding: 0; }
  .extraction-state { padding: 20px 24px; background: white; border: 1px solid #e0e0e0; border-radius: 6px; font-size: 14px; color: #666; }
  .extraction-failed { color: #c0392b; }
  .extraction-failed .error-detail { margin-top: 8px; font-size: 13px; font-family: monospace; background: #fde8e8; padding: 10px 14px; border-radius: 4px; }

  .section-block { background: white; border: 1px solid #e0e0e0; border-radius: 6px; padding: 20px 24px; margin-bottom: 12px; }
  .section-block h2 { font-size: 18px; color: #1a1a1a; margin: 0 0 12px; }
  .section-block h3 { font-size: 15px; color: #1a1a1a; margin: 0 0 10px; }
  .section-block h4 { font-size: 14px; color: #444; margin: 0 0 8px; }
  .section-content { font-size: 14px; color: #333; line-height: 1.7; white-space: pre-wrap; }
  .table-block { margin-top: 16px; overflow-x: auto; }
  .table-block table { border-collapse: collapse; font-size: 13px; width: 100%; }
  .table-block th, .table-block td { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; vertical-align: top; }
  .table-block th { background: #f5f5f5; font-weight: 600; }

  .ack-section { margin-top: 28px; border-top: 1px solid #e8e8e8; padding-top: 28px; }
  .ack-section > h3 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 24px; }
  .section-divider { border: none; border-top: 1px solid #e8e8e8; margin: 36px 0; }
  .ack-placeholder { font-size: 14px; color: #bbb; font-style: italic; }
  .ack-generating { font-size: 14px; color: #555; }
  .ack-retry-btn { margin-top: 12px; padding: 8px 18px; background: #3D5A80; color: white; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
  .ack-retry-btn:hover { background: #2e4565; }
  .ack-block { margin-bottom: 28px; }
  .ack-block h4 { font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin: 0 0 10px; }
  .ack-prose { font-size: 15px; color: #222; line-height: 1.75; }
  .ack-framework { margin-bottom: 14px; padding: 14px 16px; background: white; border: 1px solid #e8e8e8; border-radius: 6px; }
  .ack-framework-name { font-size: 14px; font-weight: 700; color: #1a1a1a; margin-bottom: 4px; }
  .ack-framework-claim { font-size: 14px; color: #333; line-height: 1.6; }
  .ack-framework-source { font-size: 12px; color: #bbb; margin-top: 4px; }
  .ack-connection { margin-bottom: 14px; padding: 14px 16px; background: white; border: 1px solid #e8e8e8; border-radius: 6px; }
  .ack-connection-claim { font-size: 13px; color: #555; font-style: italic; margin-bottom: 6px; }
  .ack-rel-tag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-right: 8px; font-weight: 600; }
  .rel-supports { background: #d5f5e3; color: #1e8449; }
  .rel-extends { background: #d6eaf8; color: #1a5276; }
  .rel-challenges { background: #fde8e8; color: #922b21; }
  .rel-adjacent { background: #f2f3f4; color: #7f8c8d; }
  .ack-connection-reasoning { font-size: 14px; color: #333; line-height: 1.6; }
  .ack-questions ol { margin: 0; padding-left: 20px; }
  .ack-questions li { font-size: 14px; color: #333; line-height: 1.7; margin-bottom: 8px; }
  .ack-meta { margin-top: 24px; font-size: 12px; color: #bbb; border-top: 1px solid #f0f0f0; padding-top: 12px; }
</style>
<script src="{{ url_for('static', filename='js/observability.js') }}"></script>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Field Work</h1>
  </div>
  {{ nav | safe }}

  <a class="back-link" href="/field">&larr; Back to The Field</a>

  <div class="artifact-header">
    <h2>{{ artifact.title or artifact.filename }}</h2>
    <div class="artifact-meta-row">
      <span class="artifact-tag tag-type">{{ artifact.type or 'other' }}</span>
      <span class="artifact-tag {% if artifact.extraction_status == 'complete' %}tag-complete{% elif artifact.extraction_status == 'failed' %}tag-failed{% else %}tag-pending{% endif %}">
        extraction: {{ artifact.extraction_status or 'pending' }}
      </span>
      {% if artifact.acknowledgment_status == 'complete' %}<span class="artifact-tag tag-complete">&#10003; First read complete</span>
      {% elif artifact.acknowledgment_status == 'generating' %}<span class="artifact-tag tag-generating">Charlie is reading&#8230;</span>
      {% elif artifact.acknowledgment_status == 'failed' %}<span class="artifact-tag tag-failed">Read failed</span>
      {% elif artifact.acknowledgment_status == 'pending' %}<span class="artifact-tag tag-pending">Awaiting read</span>
      {% endif %}
    </div>
    <div class="artifact-meta-row">
      {{ artifact.format | upper if artifact.format else '' }}
      {% if artifact.word_count %}&middot; {{ artifact.word_count }} words{% endif %}
      {% if artifact.uploaded_at %}&middot; {{ artifact.uploaded_at[:10] }}{% endif %}
    </div>
    {% if artifact.description %}
    <div class="artifact-description">{{ artifact.description }}</div>
    {% endif %}
    <a class="download-link" href="/field/originals/{{ artifact.id }}" download="{{ artifact.filename }}">Download original &darr;</a>
  </div>

  {# ── Charlie's First Read (top) ── #}
  <div class="ack-section">
    <h3>Charlie's First Read</h3>

    {% if artifact.acknowledgment_status == 'generating' %}
    <p class="ack-generating" style="margin-bottom:14px;">Charlie is reading this document&hellip; If this has been sitting here a while, it may have gotten stuck.</p>
    <button class="ack-retry-btn" onclick="retryAcknowledgment('{{ artifact.id }}')">Generate first read</button>
    <div id="retry-status" style="margin-top:10px;font-size:13px;color:#555;"></div>

    {% elif artifact.acknowledgment_status == 'failed' %}
    <p style="color:#c0392b;font-size:14px;">Acknowledgment generation failed.</p>
    {% if artifact.acknowledgment_error %}
    <div style="font-size:13px;font-family:monospace;background:#fde8e8;padding:10px 14px;border-radius:4px;color:#922b21;margin-bottom:12px;">{{ artifact.acknowledgment_error }}</div>
    {% endif %}
    <button class="ack-retry-btn" onclick="retryAcknowledgment('{{ artifact.id }}')">Retry acknowledgment</button>
    <div id="retry-status" style="margin-top:10px;font-size:13px;color:#555;"></div>

    {% elif artifact.acknowledgment_status == 'complete' and acknowledgment %}
    {% set s = acknowledgment.sections %}

    <div class="ack-block">
      <h4>What I read this to be arguing</h4>
      <p class="ack-prose">{{ s.what_i_read_this_to_be_arguing }}</p>
    </div>

    {% if s.frameworks_extracted %}
    <div class="ack-block">
      <h4>Frameworks extracted</h4>
      {% for fw in s.frameworks_extracted %}
      <div class="ack-framework">
        <div class="ack-framework-name">{{ fw.name }}</div>
        <div class="ack-framework-claim">{{ fw.claim }}</div>
        {% if fw.source_section %}<div class="ack-framework-source">Source: {{ fw.source_section }}</div>{% endif %}
      </div>
      {% endfor %}
    </div>
    {% endif %}

    <div class="ack-block">
      <h4>Empirical foundation</h4>
      <p class="ack-prose">{{ s.empirical_foundation }}</p>
    </div>

    {% if s.connections_to_current_thesis %}
    <div class="ack-block">
      <h4>Connections to current thesis</h4>
      {% for conn in s.connections_to_current_thesis %}
      <div class="ack-connection">
        <div class="ack-connection-claim">&ldquo;{{ conn.thesis_claim }}&rdquo;</div>
        <span class="ack-rel-tag rel-{{ conn.relationship }}">{{ conn.relationship }}</span>
        <span class="ack-connection-reasoning">{{ conn.reasoning }}</span>
      </div>
      {% endfor %}
    </div>
    {% endif %}

    {% if s.open_questions %}
    <div class="ack-block ack-questions">
      <h4>Open questions</h4>
      <ol>
        {% for q in s.open_questions %}<li>{{ q }}</li>{% endfor %}
      </ol>
    </div>
    {% endif %}

    {% set notes = acknowledgment.generation_notes %}
    <div class="ack-meta">
      Generated {{ acknowledgment.generated_at[:10] if acknowledgment.generated_at else '' }}
      &middot; {{ notes.duration_seconds }}s
      &middot; {{ notes.model }}
      &middot; {{ notes.word_count_read }} words read
    </div>

    {% else %}
    <p class="ack-placeholder" style="margin-bottom:14px;">Charlie hasn't read this yet.</p>
    {% if artifact.extraction_status == 'complete' %}
    <button class="ack-retry-btn" onclick="retryAcknowledgment('{{ artifact.id }}')">Generate first read</button>
    <div id="retry-status" style="margin-top:10px;font-size:13px;color:#555;"></div>
    {% endif %}
    {% endif %}
  </div>

  <hr class="section-divider">

  {# ── Extracted Content ── #}
  <div class="extracted-header">
    <h3>Extracted Content</h3>
    {% if artifact.word_count %}<span class="word-count">{{ artifact.word_count }} words</span>{% endif %}
  </div>

  {% if artifact.extraction_status == 'pending' %}
  <div class="extraction-state">Extraction in progress&hellip;</div>

  {% elif artifact.extraction_status == 'failed' %}
  <div class="extraction-state extraction-failed">
    Extraction failed.
    {% if artifact.extraction_error %}
    <div class="error-detail">{{ artifact.extraction_error }}</div>
    {% endif %}
    <p style="margin-top:12px;font-size:13px;color:#999">Re-upload the file to retry.</p>
  </div>

  {% elif extracted %}

  {% if extracted.extraction_notes %}
  <div class="notes-block">
    <strong>Extraction notes:</strong>
    <ul>{% for n in extracted.extraction_notes %}<li>{{ n }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  {% for section in extracted.sections %}
  {% set s_idx = loop.index0 %}
  <div class="section-block">
    {% if section.heading %}
      {% if section.level == 1 %}<h2>{{ section.heading }}</h2>
      {% elif section.level == 2 %}<h3>{{ section.heading }}</h3>
      {% elif section.level >= 3 %}<h4>{{ section.heading }}</h4>
      {% else %}<h3>{{ section.heading }}</h3>
      {% endif %}
    {% endif %}
    {% if section.content %}
    <div class="section-content">{{ section.content }}</div>
    {% endif %}
    {% for tbl in extracted.tables %}
    {% if tbl.section_index == s_idx and tbl.rows %}
    <div class="table-block">
      <table>
        {% for row in tbl.rows %}
        {% if loop.first %}
        <tr>{% for cell in row %}<th>{{ cell }}</th>{% endfor %}</tr>
        {% else %}
        <tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>
        {% endif %}
        {% endfor %}
      </table>
    </div>
    {% endif %}
    {% endfor %}
  </div>
  {% endfor %}

  {% else %}
  <div class="extraction-state">No extracted content available.</div>
  {% endif %}

  <div class="footer">Charlie — Entertainment Industry Intelligence</div>
</div>
<script>
function retryAcknowledgment(artifactId) {
  var btn = document.querySelector('.ack-retry-btn');
  var status = document.getElementById('retry-status');
  btn.disabled = true;
  btn.textContent = 'Charlie is reading\u2026';
  status.textContent = 'This may take up to 90 seconds. Page will refresh automatically.';

  fetch('/api/field/work/' + artifactId + '/reacknowledge', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status !== 'ok') {
        btn.disabled = false;
        btn.textContent = 'Generate first read';
        status.textContent = 'Failed: ' + (data.message || 'unknown error');
        return;
      }
      // Poll every 8 seconds until complete or failed
      var polls = 0;
      var interval = setInterval(function() {
        polls++;
        fetch('/api/field/work/' + artifactId + '/status')
          .then(function(r) { return r.json(); })
          .then(function(d) {
            if (d.acknowledgment_status === 'complete') {
              clearInterval(interval);
              window.location.reload();
            } else if (d.acknowledgment_status === 'failed') {
              clearInterval(interval);
              btn.disabled = false;
              btn.textContent = 'Generate first read';
              status.textContent = 'Generation failed — check logs.';
            } else if (polls >= 20) {
              clearInterval(interval);
              status.textContent = 'Still running — refresh the page in a moment.';
            }
          })
          .catch(function() { /* keep polling */ });
      }, 8000);
    })
    .catch(function(err) {
      btn.disabled = false;
      btn.textContent = 'Generate first read';
      status.textContent = 'Request failed: ' + err.message;
    });
}
</script>
</body>
</html>"""


_ALLOWED_EXTENSIONS = {"docx", "xlsx", "pdf", "pptx", "md", "txt"}
_ARTIFACT_TYPES = {"research", "memo", "notes", "reference", "other"}
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


def _safe_filename(filename: str) -> str:
    """Sanitize upload filename: keep extension, replace unsafe chars."""
    filename = os.path.basename(filename)
    filename = re.sub(r"[^\w.\-]", "_", filename)
    return filename[:200] or "upload"


def _make_artifact_id(title: str) -> str:
    """Generate fw_YYYYMMDD_{slug} ID, unique among existing artifacts."""
    from datetime import date as _date
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "untitled"
    base = f"fw_{_date.today().strftime('%Y%m%d')}_{slug}"
    candidate = base
    suffix = 2
    while (config.field_dir / "artifacts" / f"{candidate}.json").exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


@app.route("/field/work/<artifact_id>")
def show_field_work(artifact_id: str):
    _log.debug("request_received", route="/field/work/<id>", method="GET", artifact_id=artifact_id)
    artifact = state.load_field_artifact(artifact_id)
    if not artifact:
        return "Not found", 404
    extracted = state.load_field_extracted(artifact_id)
    acknowledgment = load_acknowledgment(artifact_id)
    _log.info("request_completed", route="/field/work/<id>", method="GET", artifact_id=artifact_id)
    return render_template_string(
        FIELD_WORK_DETAIL_TEMPLATE,
        artifact=artifact,
        extracted=extracted,
        acknowledgment=acknowledgment,
        nav=nav_html("field"),
    )


@app.route("/api/field/<artifact_id>", methods=["DELETE"])
def api_field_delete(artifact_id: str):
    """Delete a Field Work artifact and all associated files."""
    _log.info("request_received", route="/api/field/<id>", method="DELETE", artifact_id=artifact_id)
    artifact = state.load_field_artifact(artifact_id)
    if not artifact:
        return jsonify({"error": "not found"}), 404

    outcomes = state.delete_field_artifact(artifact_id)

    if any(v == "failed" for v in outcomes.values()):
        _log.error("field_artifact_delete_partial", artifact_id=artifact_id, outcomes=outcomes)
        return jsonify({"error": "delete failed", "outcomes": outcomes}), 500

    _log.info("field_artifact_deleted", artifact_id=artifact_id)
    return jsonify({"deleted": artifact_id})


@app.route("/api/field/work/<artifact_id>/reacknowledge", methods=["POST"])
def api_field_reacknowledge(artifact_id: str):
    _log.info("request_received", route="/api/field/work/<id>/reacknowledge",
              method="POST", artifact_id=artifact_id)
    artifact = state.load_field_artifact(artifact_id)
    if not artifact:
        return jsonify({"status": "error", "message": "Artifact not found"}), 404
    if artifact.get("extraction_status") != "complete":
        return jsonify({"status": "error", "message": "Extraction must complete before acknowledgment"}), 400

    artifact["acknowledgment_status"] = "generating"
    artifact.pop("acknowledgment_error", None)
    state.save_field_artifact(artifact)

    def _run_ack(art):
        import threading
        bound = _log.bind(artifact_id=art["id"], thread=threading.current_thread().name)
        try:
            run_acknowledge(art)
            ack_path = str(config.field_dir / "acknowledgments" / f"{art['id']}.json")
            art["acknowledgment_status"] = "complete"
            art["acknowledgment_path"] = ack_path
        except Exception as exc:
            bound.error("reacknowledge_failed", exc_info=True)
            art["acknowledgment_status"] = "failed"
            art["acknowledgment_error"] = str(exc)
        state.save_field_artifact(art)

    import threading
    threading.Thread(target=_run_ack, args=(dict(artifact),), daemon=True).start()

    return jsonify({"status": "ok", "id": artifact_id, "acknowledgment_status": "generating"})


@app.route("/api/field/work/<artifact_id>/status", methods=["GET"])
def api_field_work_status(artifact_id: str):
    artifact = state.load_field_artifact(artifact_id)
    if not artifact:
        return jsonify({"status": "error", "message": "Artifact not found"}), 404
    return jsonify({
        "status": "ok",
        "id": artifact_id,
        "acknowledgment_status": artifact.get("acknowledgment_status", "pending"),
        "extraction_status": artifact.get("extraction_status", "pending"),
    })


@app.route("/field/originals/<artifact_id>")
def download_field_original(artifact_id: str):
    _log.debug("request_received", route="/field/originals/<id>", method="GET", artifact_id=artifact_id)
    artifact = state.load_field_artifact(artifact_id)
    if not artifact:
        return "Not found", 404
    original_path = config.field_dir / "originals" / artifact["stored_filename"]
    if not original_path.exists():
        return "File not found", 404
    _log.info("request_completed", route="/field/originals/<id>", method="GET", artifact_id=artifact_id)
    return send_file(original_path, as_attachment=True, download_name=artifact.get("filename", artifact["stored_filename"]))


@app.route("/api/field/upload", methods=["POST"])
def upload_field_work():
    bound = _log.bind(route="/api/field/upload", method="POST")
    bound.info("upload_received")

    # ── Validate inputs ──────────────────────────────────────────────────
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"status": "error", "message": "Empty filename"}), 400

    title = request.form.get("title", "").strip()
    if not title:
        # Default to filename sans extension
        title = f.filename.rsplit(".", 1)[0] if "." in f.filename else f.filename
    title = title[:200]

    artifact_type = request.form.get("type", "").strip()
    if artifact_type not in _ARTIFACT_TYPES:
        return jsonify({"status": "error", "message": f"Invalid type. Must be one of: {', '.join(sorted(_ARTIFACT_TYPES))}"}), 400

    description = request.form.get("description", "").strip()[:1000]

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        return jsonify({"status": "error", "message": f"Unsupported format '.{ext}'. Allowed: {', '.join('.' + e for e in sorted(_ALLOWED_EXTENSIONS))}"}), 400

    # Explicit size check (MAX_CONTENT_LENGTH gives 413; we want 400)
    f.seek(0, 2)
    file_size = f.tell()
    f.seek(0)
    if file_size > _MAX_UPLOAD_BYTES:
        return jsonify({"status": "error", "message": f"File too large ({file_size // (1024*1024)} MB). Maximum is 25 MB."}), 400

    # ── Generate artifact ID ─────────────────────────────────────────────
    artifact_id = _make_artifact_id(title)
    safe_name = _safe_filename(f.filename)
    stored_filename = f"{artifact_id}.{ext}"
    original_path = config.field_dir / "originals" / stored_filename
    bound = bound.bind(artifact_id=artifact_id)

    # ── Save raw file atomically ─────────────────────────────────────────
    tmp_path = original_path.with_suffix(original_path.suffix + ".tmp")
    try:
        original_path.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(tmp_path))
        os.replace(tmp_path, original_path)
        bound.info("file_saved", path=str(original_path), size=file_size)
    except Exception:
        bound.error("field_upload_save_failed", exc_info=True)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"status": "error", "message": "Failed to save file"}), 500

    # ── Extract content ──────────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    extraction_status = "pending"
    extraction_error = None
    extracted_title = None
    word_count = None
    extracted_path = None

    bound.info("extraction_started", ext=ext)
    try:
        extracted = extract_artifact(artifact_id, original_path, ext)
        extraction_status = "complete"
        extracted_title = extracted.get("title_extracted")
        word_count = extracted.get("word_count")
        extracted_path = extracted.get("extracted_path")
        bound.info("extraction_complete", word_count=word_count, sections=len(extracted.get("sections", [])))
    except Exception as exc:
        extraction_status = "failed"
        extraction_error = str(exc)
        bound.error("extraction_failed", error=extraction_error, exc_info=True)

    # ── Build and save artifact record ───────────────────────────────────
    # Use document-extracted title if user didn't provide a custom one
    display_title = title if title != f.filename.rsplit(".", 1)[0] else (extracted_title or title)

    artifact = {
        "id": artifact_id,
        "filename": safe_name,
        "stored_filename": stored_filename,
        "format": ext,
        "title": display_title,
        "type": artifact_type,
        "description": description,
        "word_count": word_count,
        "uploaded_at": now,
        "extraction_status": extraction_status,
        "extraction_error": extraction_error,
        "extracted_path": extracted_path,
        "acknowledgment_status": "pending",
        "acknowledgment_path": None,
    }

    try:
        state.save_field_artifact(artifact)
    except Exception:
        bound.error("field_save_artifact_failed", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to save artifact metadata"}), 500

    # ── Run acknowledgment in background (only if extraction succeeded) ────
    # Runs in a daemon thread so the upload response returns immediately,
    # avoiding Railway's ~60s request timeout on the ~70s Opus call.
    if extraction_status == "complete":
        artifact["acknowledgment_status"] = "generating"
        state.save_field_artifact(artifact)

        def _run_ack(art):
            import threading
            _bound = _log.bind(artifact_id=art["id"], thread=threading.current_thread().name)
            try:
                ack = run_acknowledge(art)
                ack_path = str(config.field_dir / "acknowledgments" / f"{art['id']}.json")
                art["acknowledgment_status"] = "complete"
                art["acknowledgment_path"] = ack_path
            except Exception as exc:
                _bound.error("acknowledgment_failed_in_upload", exc_info=True)
                art["acknowledgment_status"] = "failed"
                art["acknowledgment_error"] = str(exc)
            state.save_field_artifact(art)

        import threading
        t = threading.Thread(target=_run_ack, args=(dict(artifact),), daemon=True)
        t.start()

    bound.info("upload_complete",
               extraction_status=extraction_status,
               acknowledgment_status=artifact["acknowledgment_status"])
    return jsonify({
        "status": "ok",
        "id": artifact_id,
        "filename": safe_name,
        "format": ext,
        "title": display_title,
        "type": artifact_type,
        "word_count": word_count,
        "uploaded_at": now,
        "extraction_status": extraction_status,
        "acknowledgment_status": artifact["acknowledgment_status"],
    })



# ── Oven Templates & Routes ───────────────────────────────────────────────────

_OVEN_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — The Oven</title>
<style>
  """ + SHARED_STYLES + """
  .prompt-form { margin-bottom: 40px; }
  .prompt-label { font-size: 13px; color: #666; margin-bottom: 8px; display: block; }
  .prompt-input { width: 100%; padding: 12px 14px; border: 1px solid #ddd; border-radius: 6px;
                  font-size: 15px; font-family: inherit; resize: vertical; min-height: 80px;
                  background: white; color: #1a1a1a; }
  .prompt-input:focus { outline: none; border-color: #aaa; }
  .prompt-row { display: flex; gap: 10px; align-items: flex-start; margin-top: 10px; }
  .generate-btn { padding: 10px 22px; background: #1a1a1a; color: white; border: none;
                  border-radius: 6px; font-size: 14px; cursor: pointer; white-space: nowrap; }
  .generate-btn:hover { background: #333; }
  .generate-btn:disabled { background: #bbb; cursor: not-allowed; }
  .generating-msg { font-size: 13px; color: #999; display: none; padding-top: 12px; }

  .takes-header { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #bbb;
                  margin-bottom: 12px; }
  .take-item { background: white; border: 1px solid #e0e0e0; border-radius: 6px;
               padding: 16px 18px; margin-bottom: 10px; position: relative; }
  .take-item-title { font-size: 15px; font-weight: 500; margin-bottom: 4px; }
  .take-item-title a { color: #1a1a1a; text-decoration: none; }
  .take-item-title a:hover { text-decoration: underline; }
  .take-item-meta { font-size: 12px; color: #bbb; }
  .take-delete-btn { position: absolute; top: 12px; right: 12px; background: none; border: none;
                     cursor: pointer; color: #ccc; font-size: 16px; line-height: 1; padding: 2px 6px; }
  .take-delete-btn:hover { color: #c0392b; }
</style>
</head>
<body>
<div class="container">
  {{ nav | safe }}
  <div class="header">
    <h1>The Oven</h1>
    <div class="sub">On-demand strategic takes</div>
  </div>

  <div class="prompt-form">
    <label class="prompt-label">What do you want a take on?</label>
    <textarea class="prompt-input" id="oven-prompt" placeholder="e.g. Katherine Pope and the Sony nonfiction restructuring, what's Audiochuck's next move, where does Netflix's podcast strategy land..."></textarea>
    <div class="prompt-row">
      <button class="generate-btn" id="generate-btn" onclick="generateTake()">Generate Take</button>
      <span class="generating-msg" id="generating-msg">Generating... this takes 30-60 seconds.</span>
    </div>
  </div>

  {% if takes %}
  <div class="takes-header">Recent Takes</div>
  {% for t in takes %}
  <div class="take-item" id="take-{{ t.take_id }}">
    <div class="take-item-title">
      <a href="/oven/{{ t.take_id }}">{{ t.prompt[:80] }}{% if t.prompt|length > 80 %}...{% endif %}</a>
    </div>
    <div class="take-item-meta">{{ t.generated_at[:10] }}</div>
    <button class="take-delete-btn" data-id="{{ t.take_id }}"
            data-prompt="{{ t.prompt[:60] | e }}"
            onclick="deleteTake(this.dataset.id, this.dataset.prompt, this)">×</button>
  </div>
  {% endfor %}
  {% else %}
  <p class="empty">No takes yet. Enter a prompt above to generate the first one.</p>
  {% endif %}
</div>

<script>
async function generateTake() {
  const prompt = document.getElementById('oven-prompt').value.trim();
  if (!prompt) { return; }
  const btn = document.getElementById('generate-btn');
  const msg = document.getElementById('generating-msg');
  btn.disabled = true;
  msg.style.display = 'inline';

  try {
    const resp = await fetch('/api/oven/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt}),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert('Error: ' + (err.error || resp.status));
      return;
    }
    const data = await resp.json();
    window.location.href = '/oven/' + data.take_id;
  } catch (e) {
    alert('Network error: ' + e.message);
  } finally {
    btn.disabled = false;
    msg.style.display = 'none';
  }
}

document.getElementById('oven-prompt').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { generateTake(); }
});

async function deleteTake(id, prompt, btn) {
  if (!confirm('Delete take: "' + prompt + '"?')) { return; }
  try {
    const resp = await fetch('/api/oven/' + id, {method: 'DELETE'});
    if (!resp.ok) { alert('Delete failed'); return; }
    const wrapper = document.getElementById('take-' + id);
    if (wrapper) { wrapper.remove(); }
  } catch (e) {
    alert('Network error: ' + e.message);
  }
}
</script>
</body>
</html>"""

_OVEN_DETAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — Take</title>
<style>
  """ + SHARED_STYLES + """
  .back-link { font-size: 13px; color: #3D5A80; text-decoration: none; display: inline-block; margin-bottom: 20px; }
  .back-link:hover { text-decoration: underline; }
  .take-prompt { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
  .take-meta { font-size: 13px; color: #bbb; margin-bottom: 32px; }
  .section-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #bbb;
                   margin-bottom: 10px; margin-top: 28px; }
  .section-body { font-size: 15px; line-height: 1.6; color: #1a1a1a; }
  .section-list { list-style: none; padding: 0; margin: 0; }
  .section-list li { font-size: 15px; line-height: 1.5; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
  .section-list li:last-child { border-bottom: none; }
  .section-list li::before { content: "—"; color: #bbb; margin-right: 10px; }
  .notes-block { margin-top: 32px; padding-top: 16px; border-top: 1px solid #e0e0e0;
                 font-size: 13px; color: #999; font-style: italic; }
  .download-link { display: inline-block; margin-top: 10px; font-size: 13px; color: #3D5A80; text-decoration: none; }
  .download-link:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  {{ nav | safe }}
  <a class="back-link" href="/oven">← The Oven</a>

  <div class="take-prompt">{{ take_record.prompt }}</div>
  <div class="take-meta">{{ take_record.generated_at[:10] }}</div>

  {% set t = take_record.take %}

  {% if t.situation %}
  <div class="section-label">Situation</div>
  <div class="section-body">{{ t.situation }}</div>
  {% endif %}

  {% if t.whats_on_their_mind %}
  <div class="section-label">What's on their mind</div>
  <div class="section-body">{{ t.whats_on_their_mind }}</div>
  {% endif %}

  {% if t.worth_raising %}
  <div class="section-label">Worth raising</div>
  <ul class="section-list">
    {% for item in t.worth_raising %}<li>{{ item }}</li>{% endfor %}
  </ul>
  {% endif %}

  {% if t.watch_for %}
  <div class="section-label">Watch for</div>
  <ul class="section-list">
    {% for item in t.watch_for %}<li>{{ item }}</li>{% endfor %}
  </ul>
  {% endif %}

  {% if t.open_loops %}
  <div class="section-label">Open loops</div>
  <ul class="section-list">
    {% for item in t.open_loops %}<li>{{ item }}</li>{% endfor %}
  </ul>
  {% endif %}

  {% if t.generation_notes %}
  <div class="notes-block">{{ t.generation_notes }}</div>
  {% endif %}

  <div style="margin-top: 24px;">
    <a class="download-link" href="/oven/{{ take_record.take_id }}/download">↓ Download JSON</a>
  </div>
</div>
</body>
</html>"""


@app.route("/oven")
def show_oven():
    _log.debug("request_received", route="/oven", method="GET")
    takes = state.list_takes()
    return render_template_string(_OVEN_TEMPLATE, nav=nav_html("oven"), takes=takes)


@app.route("/oven/<take_id>")
def show_take(take_id: str):
    _log.debug("request_received", route=f"/oven/{take_id}", method="GET")
    take_record = state.load_take(take_id)
    if not take_record:
        return "Take not found", 404
    return render_template_string(_OVEN_DETAIL_TEMPLATE, nav=nav_html("oven"), take_record=take_record)


@app.route("/oven/<take_id>/download")
def download_take(take_id: str):
    _log.debug("request_received", route=f"/oven/{take_id}/download", method="GET")
    take_record = state.load_take(take_id)
    if not take_record:
        return "Take not found", 404
    import io
    buf = io.BytesIO(json.dumps(take_record, indent=2).encode("utf-8"))
    slug = take_record["prompt"][:40].replace(" ", "_").replace("/", "-")
    filename = f"take_{take_id[:8]}_{slug}.json"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="application/json")


@app.route("/api/oven/generate", methods=["POST"])
def api_oven_generate():
    data = request.json or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    _log.info("request_received", route="/api/oven/generate", method="POST",
              prompt_length=len(prompt))
    try:
        record = run_oven(prompt)
        _log.info("request_completed", route="/api/oven/generate", take_id=record["take_id"])
        return jsonify({"take_id": record["take_id"]})
    except Exception as exc:
        _log.error("oven_generate_failed", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/oven/<take_id>", methods=["DELETE"])
def api_oven_delete(take_id: str):
    _log.info("request_received", route=f"/api/oven/{take_id}", method="DELETE")
    outcome = state.delete_take(take_id)
    if outcome == "missing":
        return jsonify({"error": "not found"}), 404
    if outcome == "failed":
        return jsonify({"error": "delete failed"}), 500
    return jsonify({"deleted": take_id})


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    data = request.json
    _log.info("request_received", route="/api/feedback", method="POST",
              signal_type=data.get("signal_type"), rating=data.get("rating"),
              brief_date=data.get("brief_date"))
    add_rating(
        signal_headline=data.get("headline", ""),
        signal_type=data.get("signal_type", "other"),
        rating=int(data.get("rating", 5)),
        brief_date=data.get("brief_date", ""),
    )
    _log.info("request_completed", route="/api/feedback", method="POST")
    return jsonify({"status": "ok"})


@app.route("/api/feedback/summary")
def feedback_summary():
    feedback = load_feedback()
    return jsonify(feedback.get("summary", {}))


@app.route("/run", methods=["GET", "POST"])
def run_pipeline():
    _log.debug("request_received", route="/run", method=request.method)
    if request.method == "GET":
        return render_template_string(RUN_TEMPLATE, nav=nav_html("run"))

    import threading
    def _run():
        try:
            from orchestrator import run_daily_pipeline
            run_daily_pipeline()
        except Exception as e:
            _log.error("pipeline_error", trigger="web", exc_info=True)
            print(f"[Web] Pipeline error: {e}")

    _log.info("pipeline_triggered", trigger="web")
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
        thesis_day = int(os.environ.get("THESIS_DAY", "5"))
        tz = os.environ.get("BRIEF_TIMEZONE", "America/Los_Angeles")

        _DAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        thesis_day_name = _DAY_NAMES[thesis_day] if 0 <= thesis_day <= 6 else str(thesis_day)
        print(f"[Scheduler] Started. Brief daily at {brief_hour}:00 {tz}. Thesis {thesis_day_name}s at {brief_hour + 1}:00.")

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


# ── Client Error Capture ─────────────────────────────────────────────────

_client_error_rl: dict = defaultdict(deque)
_RL_WINDOW = 300   # 5 minutes
_RL_MAX = 50


def _rl_check(key: tuple) -> bool:
    """Return True if this key is over the rate limit (caller should drop)."""
    now = time.monotonic()
    q = _client_error_rl[key]
    while q and q[0] < now - _RL_WINDOW:
        q.popleft()
    if len(q) >= _RL_MAX:
        return True
    q.append(now)
    return False


@app.route("/api/client-error", methods=["POST"])
def api_client_error():
    """Receive a frontend error report and write it to the log stream."""
    data = request.get_json(silent=True)
    if data is None:
        _log.warning("client_error_bad_payload", reason="malformed_json",
                     remote_addr=request.remote_addr)
        return "", 400

    message = str(data.get("message") or "")
    if not message:
        return "", 400

    rl_key = (
        str(data.get("source") or ""),
        int(data.get("lineno") or 0),
        int(data.get("colno") or 0),
    )
    if _rl_check(rl_key):
        return "", 200  # silently drop — over rate limit

    _log.error("client_error",
        message=message[:500],
        source=str(data.get("source") or "")[:200],
        lineno=data.get("lineno"),
        colno=data.get("colno"),
        stack=str(data.get("stack") or "")[:2000],
        url=str(data.get("url") or "")[:500],
        user_agent=str(data.get("user_agent") or "")[:300],
        event_type=str(data.get("event_type") or "error"),
        context=data.get("context") or {},
    )
    return "", 200


# ── Admin Logs ────────────────────────────────────────────────────────────

_ADMIN_LOG_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie Logs</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'SF Mono', 'Menlo', 'Consolas', monospace; font-size: 12px;
         background: #1a1a1a; color: #d4d4d4; padding: 16px; }
  h1 { font-size: 16px; font-weight: 600; color: #ffffff; margin-bottom: 6px; }
  .meta { font-size: 11px; color: #666; margin-bottom: 16px; }
  .filters { margin-bottom: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
  .filters a { font-size: 11px; color: #888; text-decoration: none; padding: 3px 8px;
               border: 1px solid #333; border-radius: 3px; }
  .filters a:hover { color: #fff; border-color: #555; }
  .filters a.active { color: #fff; border-color: #888; background: #333; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 6px 10px; color: #666; font-weight: 500;
       border-bottom: 1px solid #333; white-space: nowrap; }
  td { padding: 5px 10px; vertical-align: top; border-bottom: 1px solid #222; }
  tr:hover td { background: #222; }
  .ts { color: #666; white-space: nowrap; }
  .lvl-error { color: #e06c75; font-weight: 600; }
  .lvl-warning { color: #e5c07b; font-weight: 600; }
  .lvl-info { color: #98c379; }
  .lvl-debug { color: #555; }
  .logger { color: #61afef; }
  .event { color: #d4d4d4; }
  .ctx { color: #888; font-size: 11px; }
  .empty { color: #444; font-style: italic; padding: 20px 0; }
</style>
</head>
<body>
<h1>Charlie Logs</h1>
<div class="meta">{{ count }} entries &mdash; {{ filter_desc }}</div>
<div class="filters">
  <a href="{{ base_url }}" class="{{ 'active' if not level_filter else '' }}">all levels</a>
  <a href="{{ base_url }}&level=error" class="{{ 'active' if level_filter == 'error' else '' }}">error</a>
  <a href="{{ base_url }}&level=warning" class="{{ 'active' if level_filter == 'warning' else '' }}">warning</a>
  <a href="{{ base_url }}&level=info" class="{{ 'active' if level_filter == 'info' else '' }}">info</a>
  <a href="{{ base_url }}&level=debug" class="{{ 'active' if level_filter == 'debug' else '' }}">debug</a>
</div>
{% if entries %}
<table>
  <thead>
    <tr>
      <th>timestamp (PT)</th>
      <th>level</th>
      <th>logger</th>
      <th>event</th>
      <th>context</th>
    </tr>
  </thead>
  <tbody>
    {% for e in entries %}
    <tr>
      <td class="ts">{{ e.ts_local }}</td>
      <td class="lvl-{{ e.level }}">{{ e.level }}</td>
      <td class="logger">{{ e.logger }}</td>
      <td class="event">{{ e.event }}</td>
      <td class="ctx">{{ e.ctx }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<div class="empty">No log entries found.</div>
{% endif %}
</body>
</html>"""


@app.route("/admin/logs")
def admin_logs():
    token = request.args.get("token", "").strip()
    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    if not admin_token or token != admin_token:
        return "Unauthorized", 401

    try:
        n = min(int(request.args.get("n", 200)), 1000)
    except (ValueError, TypeError):
        n = 200
    level_filter = request.args.get("level", "").lower().strip()
    logger_filter = request.args.get("logger", "").strip()

    log_path = config.data_dir / "logs" / "app.log"
    raw_entries = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    raw_entries.append(obj)
                except (json.JSONDecodeError, ValueError):
                    pass

    # Apply filters before slicing so ?n= refers to filtered count
    if level_filter:
        raw_entries = [e for e in raw_entries if e.get("level", "").lower() == level_filter]
    if logger_filter:
        raw_entries = [e for e in raw_entries if logger_filter in e.get("logger", "")]

    # Newest first
    raw_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    raw_entries = raw_entries[:n]

    # Format for template
    pt_offset_hours = -7  # PDT; close enough for an operator tool
    entries = []
    for obj in raw_entries:
        ts_raw = obj.get("timestamp", "")
        ts_local = ts_raw
        try:
            from datetime import timezone, timedelta
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            dt_pt = dt.astimezone(timezone(timedelta(hours=pt_offset_hours)))
            ts_local = dt_pt.strftime("%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            pass

        level = obj.get("level", "?").lower()
        logger = obj.get("logger", "")
        event = obj.get("event", "")

        # Remaining keys are context
        skip = {"timestamp", "level", "logger", "event"}
        ctx_parts = [f"{k}={json.dumps(v, default=str)}" for k, v in obj.items() if k not in skip and v is not None]
        ctx = "  ".join(ctx_parts)

        entries.append({
            "ts_local": ts_local,
            "level": level,
            "logger": logger,
            "event": event,
            "ctx": ctx,
        })

    base_url = f"/admin/logs?token={token}&n={n}"
    if logger_filter:
        base_url += f"&logger={logger_filter}"

    filter_parts = []
    if level_filter:
        filter_parts.append(f"level={level_filter}")
    if logger_filter:
        filter_parts.append(f"logger={logger_filter}")
    filter_desc = ", ".join(filter_parts) if filter_parts else f"last {n}"

    return render_template_string(
        _ADMIN_LOG_TEMPLATE,
        entries=entries,
        count=len(entries),
        filter_desc=filter_desc,
        level_filter=level_filter,
        base_url=base_url,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    seed_data()
    start_scheduler()
    app.run(host="0.0.0.0", port=port, debug=False)