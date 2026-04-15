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
        summary[signal_type] = {"count": 0, "total": 0, "avg": 0}
    summary[signal_type]["count"] += 1
    summary[signal_type]["total"] += rating
    summary[signal_type]["avg"] = round(summary[signal_type]["total"] / summary[signal_type]["count"], 2)
    feedback["summary"] = summary
    save_feedback(feedback)


# ── Shared Nav ───────────────────────────────────────────────────────────

def nav_html(active: str) -> str:
    return f"""<div class="nav">
  <a href="/" class="{'active' if active == 'brief' else ''}">The Brief</a>
  <a href="/companion" class="{'active' if active == 'companion' else ''}">Companion</a>
  <a href="/thesis" class="{'active' if active == 'thesis' else ''}">Living Thesis</a>
  <a href="/book" class="{'active' if active == 'book' else ''}">Book Project</a>
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
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Companion</h1>
    <div class="sub">{{ date_display }}</div>
  </div>

  {{ nav | safe }}

  {% if not brief %}
  <p class="empty">No brief available to respond to. <a href="/run">Run The Brief now →</a></p>
  {% else %}
  <p class="companion-intro">Respond to today's open questions. Your insights calibrate what Charlie surfaces next.</p>

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

    <button class="submit-btn" onclick="submitTier('{{ tier_key }}', '{{ tier.open_question | default('') | e }}', '{{ brief_date }}')">Submit</button>
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


@app.route("/companion")
def companion():
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

    return render_template_string(COMPANION_TEMPLATE,
                                  brief=brief,
                                  brief_date=brief_date,
                                  date_display=date_display,
                                  nav=nav_html("companion"))


@app.route("/api/companion/session", methods=["POST"])
def submit_session():
    data = request.json
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
    return jsonify({"status": "ok", "id": entry_id})


@app.route("/brief/<brief_date>")
def show_brief(brief_date):
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

    return render_template_string(BRIEF_TEMPLATE,
                                 brief=brief, signals=signals,
                                 date_display=date_display,
                                 nav=nav_html("brief"),
                                 current_date=brief_date,
                                 prev_date=prev_date,
                                 next_date=next_date)


# ── Brief API ────────────────────────────────────────────────────────────

@app.route("/api/brief/<brief_date>")
def api_brief(brief_date):
    brief_path = config.briefs_dir / f"{brief_date}.json"
    if not brief_path.exists():
        return jsonify({"error": "Brief not found"}), 404
    with open(brief_path) as f:
        data = json.load(f)
    response = jsonify(data)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


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
    if not thesis:
        _ensure_thesis_seed()
        thesis = state.load_thesis()
    return render_template_string(THESIS_TEMPLATE, thesis=thesis, nav=nav_html("thesis"))


@app.route("/book")
def show_book():
    thesis = state.load_thesis()
    if not thesis:
        _ensure_thesis_seed()
        thesis = state.load_thesis()
    return render_template_string(BOOK_TEMPLATE, thesis=thesis, nav=nav_html("book"))


def _ensure_thesis_seed():
    path = config.data_dir / "thesis" / "current.json"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = {"core_argument":"Hollywood's century-old system for finding and developing intellectual property is breaking down. The traditional pipeline — books, comics, spec scripts, licensing — was built for an era of scarcity, when a handful of broadcast slots and theatrical windows could sustain premium pricing on every title. Streaming destroyed that scarcity, demanding volume the old pipeline cannot produce. Simultaneously, the audiences studios need have migrated to platforms with fundamentally better content discovery — YouTube, TikTok, podcasting — pulled not by superior content but by superior matching. The only proven mechanism for reaching those audiences in scripted formats is through the creator brands they already trust. This is not a trend. It is a structural reorganization of how entertainment finds its way to people, and the executives and companies who understand it hold an asymmetric advantage.","updated_at":"2026-03-29T18:00:00","version":1,"forces":{"supply_exhaustion":{"summary":"The traditional IP pipeline was designed to feed a scarcity-based system. Streaming inverted this — platforms need hundreds of titles per year, not dozens. The pipeline built for scarcity cannot produce at volume, and the economics show it: option prices are inflating, conversion rates are declining, and entire categories show signs of exhaustion.","evidence":["Netflix walked away from acquiring WBD's full library — DC, Harry Potter, HBO catalog — for $82.7B. Its stock rose. The market priced legacy IP as a harvest asset, not a growth asset.","Paramount-WBD $111B merger is 85% dependent on linear cable profits — defensive consolidation, not growth investment.","Video game adaptation pipeline reached historic density in 2026 with six theatrical releases, suggesting rapid mining of a previously untapped category.","Sony Pictures Television folded its nonfiction division under scripted leadership, issued buyouts, saw senior departures — structural contraction in traditional development.","Romantasy publishing hit $600M in sales in 2024 but Hollywood has failed to convert a single major adaptation — widening gap between publishing success and screen conversion."],"confidence":"high","gaps":["No systematic longitudinal data on book option price inflation","Conversion rate from option to production across IP categories over time","Song/jukebox model depth unclear beyond Bohemian Rhapsody and Rocketman","Board game/toy IP after Barbie — no second proof point"]},"demand_migration":{"summary":"Audiences aren't choosing creator content over scripted — they're being captured by platforms with radically better discovery. YouTube, TikTok, and Spotify match individuals to content with precision no streamer replicates. The migration is a discovery problem, not a content preference problem.","evidence":["YouTube commands 11.1% of all TV streaming in the U.S., surpassing Netflix at 8.5%.","Streaming hit 47.5% of total TV viewing in December 2025, but Gen Z daily TV viewing at 36% vs. 73% for Boomers.","YouTube has 1 billion monthly active podcast viewers, 700M hours of living room podcast viewing in October 2025.","72% of podcast listeners prefer shows with video (Cumulus Media).","U.S. ad spending on creators projected at $37B in 2025, up from $13.9B four years prior — 4x broader media growth rate."],"confidence":"high","gaps":["No direct measurement of the algorithmic discovery gap between creator platforms and streamers","Demo-specific migration patterns not tracked longitudinally","Whether creator-branded shows have different retention curves — no platform publishes this","Whether any streamer uses creator audience data to improve recommendations"]},"discovery_bridge":{"summary":"Creator-branded content is the only proven mechanism for reaching algorithmically-sorted audiences in scripted formats. The creator brand functions as targeting infrastructure — more precise than ad campaigns and free to the platform.","evidence":["Netflix committed to 50-75 original video podcast shows for 2026, competing with YouTube for casual viewing at $5K-50K per episode vs. $3-10M for scripted.","Netflix pulled Ringer content off YouTube, locked iHeartMedia into exclusivity — treating creator audiences as proprietary acquisition channels.","Wondery's systematic pipeline: Dirty John, Dr. Death, Shrink Next Door, WeCrashed, Joe vs. Carole.","Audiochuck $250M valuation, Chernin investment, Matt Shanfield hired from Sony to build TV/film division.","57% of new streaming subscribers choosing ad-supported tiers, creating volume demand creator content fills.","Golden Globes introduced first podcast category in 2026."],"confidence":"medium-high","gaps":["No study directly measuring podcast-to-TV audience conversion rates","How development execs at creator-native companies protect brand differently","Economics of creator-driven audience acquisition vs. traditional marketing spend","Whether proof-of-concept model actually reduces production failure rates"]}},"ip_landscape":{"traditional":{"books":{"status":"saturating","notes":"Option prices inflating. Romantasy ($600M sales) failing to convert to screen."},"comics":{"status":"fatigued","notes":"Marvel/DC tentpole fatigue. Independent comics/manga undertapped."},"video_games":{"status":"accelerating","notes":"Six theatrical releases 2026. Last of Us, Fallout, Mario proved it. A24/Garland on Elden Ring."},"songs_jukebox":{"status":"early","notes":"Bohemian Rhapsody ($910M), Rocketman proved model. Piña Colada in development. Vast untapped catalog."},"theater":{"status":"stable","notes":"Hamilton model works but narrow pipeline. Not a volume solution."},"journalism":{"status":"evolved","notes":"Magazine-to-film pipeline absorbed into podcast-driven true crime."},"life_rights":{"status":"heavily_mined","notes":"Podcast layer gives new packaging but same underlying material. True crime fatigue risk."},"board_games_toys":{"status":"uncertain","notes":"Barbie ($1.4B) proved model but no second proof point. Mattel slate unproven."}},"creator_driven":{"podcasts":{"status":"most_mature","notes":"Systematic pipelines at Wondery, Audiochuck, Spotify Studios. Netflix entering with 50-75 shows."},"youtube":{"status":"accelerating","notes":"MrBeast/Netflix model. 11.1% TV streaming. YouTube securing NFL and Oscars (2029)."},"tiktok":{"status":"nascent","notes":"Talent discovery engine but U.S. regulatory uncertainty limits investment."},"newsletters":{"status":"early","notes":"The Optionist, Free Press/Paramount, Fox/Meet Cute. Small but high-value."},"livestreaming":{"status":"emerging","notes":"Markiplier Iron Lung in theaters 2026. A24/Backrooms. Kai Cenat/Kevin Hart film."}}},"development_function":{"summary":"Nobody is writing about what happens inside the companies building the bridge — what the development executive's job looks like when IP originates from a creator ecosystem. This is the thesis's most original territory.","key_questions":["How does the development role at Audiochuck differ from the same role at a traditional studio?","When the creator IS the brand, how do you protect IP without constraining the relationship that makes it valuable?","How should creator-driven IP be valued when the asset is audience relationship depth?","What creative control structures work when a bad adaptation damages the entire company?","Where do the bridging executives come from and what does their career path look like?"],"tracked_executives":[{"name":"Aaron Hart","company":"Wondery","title":"Head of TV and Film","track_record":"Dirty John, Dr. Death, Shrink Next Door, WeCrashed, Joe vs. Carole"},{"name":"Matt Shanfield","company":"Audiochuck","title":"Head of TV/Film Division","background":"Sony Pictures Television Nonfiction president"},{"name":"Jordan Moblo","company":"Universal Studio Group","title":"EVP Creative Acquisitions & IP Management"},{"name":"Marshall Lewy","company":"Wondery","title":"Chief Content Officer"}]},"claims":[{"id":1,"claim":"The restructuring is driven by three converging forces — supply exhaustion, demand migration, and the discovery bridge. Their interaction makes the shift structural, not cyclical.","confidence":"high","force":"all"},{"id":2,"claim":"Creator-branded content functions as audience targeting infrastructure. The value is the pre-sorted audience, not the IP.","confidence":"medium-high","force":"discovery_bridge"},{"id":3,"claim":"The development function at creator-native companies is fundamentally different from traditional studios, and building it well is the binding constraint on success.","confidence":"medium","force":"discovery_bridge"},{"id":4,"claim":"Traditional IP pipelines are declining unevenly — games and songs accelerating, books and comics saturating — but total volume is insufficient regardless.","confidence":"medium-high","force":"supply_exhaustion"},{"id":5,"claim":"Audience migration is driven by superior algorithmic discovery, not content quality decline. The solution is better discovery, not better content.","confidence":"medium","force":"demand_migration"}],"evidence":[],"book_project":{"status":"advance_offers_received","working_title":"TBD","narrative_arc":"The book tells the story of an industry losing its audience — not because it forgot how to make great content, but because the infrastructure that connected content to audiences broke, and a new one is being built by people Hollywood doesn't yet recognize as peers.","chapter_outline":[{"chapter":1,"title":"The Pipeline That Built Hollywood","focus":"The century-old system for finding stories. Why scarcity made every bet defensible.","status":"lit_review_complete"},{"chapter":2,"title":"The Exhaustion","focus":"What happens when a scarcity-based pipeline meets streaming-era volume demand.","status":"research_in_progress"},{"chapter":3,"title":"The Great Migration","focus":"Where the audience went and why. The algorithmic discovery gap as root cause.","status":"research_in_progress"},{"chapter":4,"title":"The YouTube Precedent","focus":"Fifteen years of creator ecosystem data. MCN boom and bust. What survived.","status":"lit_review_complete"},{"chapter":5,"title":"The Audio Bridge","focus":"Podcasting as the most mature creator-to-scripted pipeline. Wondery, Audiochuck, Netflix.","status":"research_in_progress"},{"chapter":6,"title":"The New Development Executive","focus":"The job nobody has defined yet. Case studies from Wondery, Audiochuck, UCP Audio.","status":"not_started"},{"chapter":7,"title":"The Discovery Problem","focus":"Why streamers can't find audiences. Creator brands as targeting infrastructure.","status":"research_in_progress"},{"chapter":8,"title":"What Comes Next","focus":"Video games, music catalogs, newsletters, livestreaming. The next wave.","status":"not_started"}]}}
    with open(path, "w") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)
    print(f"[Seed] Wrote thesis seed to {path}")


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    seed_data()
    start_scheduler()
    app.run(host="0.0.0.0", port=port, debug=False)