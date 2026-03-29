"""
Charlie Web — serves briefs and collects feedback.

Displays the daily brief with source links and a 1-10 relevance
rating for each signal/finding. Feedback is stored and dynamically
incorporated into agent prompts.

Run locally: python web.py
Deployed on Railway alongside the pipeline cron job.
"""

import json
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
    # Update running summary of signal type preferences
    summary = feedback.get("summary", {})
    if signal_type not in summary:
        summary[signal_type] = {"total_ratings": 0, "sum": 0, "avg": 5.0}
    summary[signal_type]["total_ratings"] += 1
    summary[signal_type]["sum"] += rating
    summary[signal_type]["avg"] = round(summary[signal_type]["sum"] / summary[signal_type]["total_ratings"], 1)
    feedback["summary"] = summary
    save_feedback(feedback)


def get_feedback_prompt_injection() -> str:
    """Generate a prompt fragment from accumulated feedback for agent tuning."""
    feedback = load_feedback()
    summary = feedback.get("summary", {})
    if not summary:
        return ""

    lines = ["## Feedback-Based Calibration",
             "Based on user ratings (1=irrelevant, 10=gold), these signal types have the following average relevance scores:"]
    for sig_type, data in sorted(summary.items(), key=lambda x: x[1]["avg"], reverse=True):
        n = data["total_ratings"]
        avg = data["avg"]
        if n >= 2:  # Only include types with enough data
            lines.append(f"- {sig_type}: {avg}/10 (n={n})")

    # Include recent specific low-rated signals as "avoid" examples
    recent_low = [r for r in feedback.get("ratings", [])[-50:] if r["rating"] <= 2]
    if recent_low:
        lines.append("\nRecently rated as irrelevant (avoid similar):")
        for r in recent_low[-5:]:
            lines.append(f"- \"{r['headline']}\" (rated {r['rating']}/10)")

    # Include recent high-rated signals as "more like this" examples
    recent_high = [r for r in feedback.get("ratings", [])[-50:] if r["rating"] >= 8]
    if recent_high:
        lines.append("\nRecently rated as highly relevant (find more like these):")
        for r in recent_high[-5:]:
            lines.append(f"- \"{r['headline']}\" (rated {r['rating']}/10)")

    return "\n".join(lines)


# ── HTML Template ────────────────────────────────────────────────────────

TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Charlie — The Brief</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Georgia', serif; background: #fafafa; color: #1a1a1a; line-height: 1.6; }
  .container { max-width: 680px; margin: 0 auto; padding: 40px 24px; }
  .header { border-bottom: 3px solid #1a1a1a; padding-bottom: 16px; margin-bottom: 32px; }
  .header h1 { font-size: 28px; letter-spacing: -0.5px; }
  .header .date { font-size: 14px; color: #666; margin-top: 4px; }
  .nav { margin-bottom: 24px; font-size: 13px; color: #999; }
  .nav a { color: #3D5A80; text-decoration: none; margin-right: 12px; }
  .nav a:hover { text-decoration: underline; }
  .nav a.active { color: #1a1a1a; font-weight: bold; }

  .tier { margin-bottom: 36px; }
  .tier-label { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #999; margin-bottom: 8px; }
  .tier h2 { font-size: 18px; line-height: 1.4; margin-bottom: 12px; }
  .tier .body { font-size: 15px; color: #333; margin-bottom: 12px; }
  .tier .question { font-size: 14px; color: #666; font-style: italic; padding-left: 16px; border-left: 2px solid #ddd; }
  .empty { font-size: 14px; color: #999; font-style: italic; }
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

  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e0e0e0; font-size: 12px; color: #999; }

  @media print {
    body { background: white; }
    .container { padding: 20px 0; }
    .rating, .nav { display: none; }
  }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>The Brief</h1>
    <div class="date">{{ date_display }}</div>
  </div>

  <div class="nav">
    {% for d in available_dates %}
    <a href="/brief/{{ d }}" class="{{ 'active' if d == current_date else '' }}">{{ d }}</a>
    {% endfor %}
  </div>

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
  {% endif %}

  <div class="footer">
    Generated by Charlie
  </div>
</div>

<script>
function rate(btn, rating) {
  const container = btn.closest('.rating');
  const headline = container.dataset.headline;
  const sigType = container.dataset.type;

  // Visual feedback
  container.querySelectorAll('.rating-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');

  // Send to server
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


# ── Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Redirect to today's brief or most recent available."""
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")], reverse=True)
    if available:
        return redirect(url_for("show_brief", brief_date=available[0]))
    return render_template_string(TEMPLATE, brief=None, signals=[], date_display="No briefs yet",
                                 available_dates=[], current_date="")


@app.route("/brief/<brief_date>")
def show_brief(brief_date):
    """Display a specific day's brief."""
    briefs_dir = config.briefs_dir
    available = sorted([f.stem for f in briefs_dir.glob("*.json")], reverse=True)

    # Load brief
    brief_path = briefs_dir / f"{brief_date}.json"
    brief = None
    if brief_path.exists():
        with open(brief_path) as f:
            data = json.load(f)
            brief = data.get("brief", data)

    # Load signals
    signals = state.load_signals(date.fromisoformat(brief_date))

    # Format date
    try:
        d = date.fromisoformat(brief_date)
        date_display = d.strftime("%A, %B %d, %Y")
    except ValueError:
        date_display = brief_date

    return render_template_string(TEMPLATE,
                                 brief=brief, signals=signals,
                                 date_display=date_display,
                                 available_dates=available[:14],
                                 current_date=brief_date)


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    """Receive a signal rating."""
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
    """Return the current feedback summary."""
    feedback = load_feedback()
    return jsonify(feedback.get("summary", {}))


# ── Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)