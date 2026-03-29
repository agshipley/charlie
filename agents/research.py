"""
Research Agent — iterative deep investigation with thesis-aware framing.

Runs multiple investigation cycles: broad search → gap identification → targeted
follow-up → synthesis. Incorporates the thesis analytical framework (supply
exhaustion, demand migration, discovery bridge) and prioritized source hierarchy.

Usage:
    python -m agents.research "How are podcast companies structuring TV/film divisions?"
    python -m agents.research --topic "Netflix video podcast economics" --depth 3
    python -m agents.research --from-signal data/signals/2026-03-28.json --signal-index 4
    python -m agents.research --track-exec "Aaron Hart Wondery"
"""

import json
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

from core.client import call_agent
from core.config import config
from core.state import StateManager


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
}

# ── Source Hierarchy (injected into all research prompts) ────────────────

SOURCE_HIERARCHY = """## Source Priority
When searching, prioritize in this order:
1. STRUCTURAL ANALYSTS: Matthew Ball (streaming economics), Richard Rushfield / The Ankler (studio model critique), Matthew Belloni / Puck (Hollywood deal intelligence)
2. DATA PLATFORMS: Parrot Analytics (audience demand), Nielsen (streaming share), Edison Research (podcast audiences / Infinite Dial), Luminate
3. ACADEMIC: Cunningham & Craig, Hesmondhalgh, Duffy, MidiaResearch
4. TRADE REPORTING: Deadline, Variety, THR, The Wrap, Screen International, Puck
5. CREATOR ECONOMY: Like & Subscribe News, Streaming Media, NAB Amplify"""

# ── Thesis Framework (injected into analysis and synthesis) ──────────────

THESIS_FRAMEWORK = """## Thesis Framework
Every finding should connect to one or more of these three forces:
1. SUPPLY EXHAUSTION: Traditional IP pipelines (books, comics, games, songs, theater, journalism, life rights) showing signs of saturation — inflated prices, declining hit rates, insufficient volume for streaming demand.
2. DEMAND MIGRATION: Audiences pulled to creator platforms by superior algorithmic discovery, not pushed from scripted by quality decline. Parasocial intimacy, discovery trust, niche depth, format flexibility, authenticity preference.
3. DISCOVERY BRIDGE: Creator-branded content as the only reliable mechanism for bringing migrated audiences back to scripted — the creator's audience relationship substitutes for the algorithmic discovery streamers lack."""

# ── IP Landscape Categories ──────────────────────────────────────────────

IP_LANDSCAPE = """## IP Landscape to Track

### Traditional/Institutional IP (evaluate for saturation)
Books/publishing, comic books (Marvel/DC + independent/manga), theater/Broadway, journalism/articles, life rights/true crime, video games, songs/jukebox model, board games/toys.
For each: Is this pipeline producing enough? Evidence of saturation? Option price inflation? Declining conversion rates?

### Creator-Driven IP (evaluate for growth)
Podcasts/audio, YouTube/long-form, short-form/TikTok, newsletters/Substack, livestreaming/gaming.
For each: Development volume, conversion rate option-to-production, structural advantages, barriers to adoption."""

# ── System Prompts ───────────────────────────────────────────────────────

SYSTEM_INVESTIGATE = f"""You are a research investigator for an entertainment industry intelligence system.

{SOURCE_HIERARCHY}

Search for information on the assigned topic. For each finding, report:
- The specific factual claim
- The source (publication, author, date)
- The URL
- Confidence (high/medium/low)
- Which thesis force it connects to (supply_exhaustion, demand_migration, discovery_bridge, or none)
- Follow-up questions this raises

Distinguish between what sources say and interpretation. Report conflicting information.

Return JSON:
- "findings": array of objects (claim, source, url, confidence, thesis_force, follow_up_questions)
- "summary": 2-3 sentences
- "gaps": specific questions where you couldn't find good information

Wrap in ```json``` blocks."""

SYSTEM_GAP_ANALYSIS = f"""You are a research coverage analyst for an entertainment industry thesis.

{THESIS_FRAMEWORK}
{IP_LANDSCAPE}

You will receive accumulated findings and identified gaps. Assess:
1. Coverage across the three thesis forces — which is strongest, which is thinnest?
2. Coverage across the IP landscape — which categories are well-researched, which are thin?
3. Generate 2-3 targeted search queries to fill the most important gaps
4. Identify contradictions needing resolution
5. Score saturation 0-100

Return JSON:
- "coverage_assessment": what's strong and weak
- "thesis_force_coverage": object with supply_exhaustion/demand_migration/discovery_bridge each scored 0-100
- "ip_coverage": object scoring each IP category 0-100
- "priority_queries": array of 2-3 concise search queries
- "contradictions": array of conflicting findings
- "saturation": overall 0-100

Wrap in ```json``` blocks."""

SYSTEM_SYNTHESIZE = f"""You are a research synthesizer for an entertainment industry intelligence system.

{THESIS_FRAMEWORK}

Produce a comprehensive research document that:
1. States key findings organized by the three thesis forces (supply exhaustion, demand migration, discovery bridge)
2. Maps the IP landscape — which traditional pipelines show saturation, which creator channels show growth
3. Cites sources for every claim
4. Notes where evidence is strong vs. thin
5. Identifies contradictions and open questions
6. Connects to the broader thesis about entertainment restructuring
7. Assesses audience migration patterns and demo-specific conversion opportunities
8. Notes relevant development executive moves at creator-native companies
9. Ends with specific implications and areas for further investigation

Write in clear, direct prose. No jargon. This will be read by a senior entertainment executive.

Return as plain markdown (not JSON)."""

SYSTEM_EXEC_TRACK = f"""You are a researcher tracking development executives at creator-native entertainment companies.

For the person or company specified, find:
- Full name and current title
- Company and when they joined
- Previous roles (especially traditional studio background)
- What they've produced or developed in the current role
- Success rate of their projects (critical reception, viewership if available, renewal/cancellation)
- How their approach differs from traditional studio development
- Key relationships and deals they've brokered

Also identify other executives at the same company or similar companies who hold development roles.

{SOURCE_HIERARCHY}

Return JSON:
- "executive": object with name, title, company, joined, background, track_record
- "projects": array of projects with title, status, platform, reception
- "related_executives": array of other relevant people found
- "analysis": how this person's role/approach reflects the broader restructuring

Wrap in ```json``` blocks."""


# ── Main Research Function ───────────────────────────────────────────────

def run_research(
    topic: str,
    max_depth: int = 3,
    autonomous: bool = True,
) -> dict:
    """Execute an iterative research investigation."""
    state = StateManager()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Research Agent")
    print(f"  Topic: {topic}")
    print(f"  Max depth: {max_depth} cycles")
    print(f"{'='*60}\n")

    all_findings = []
    all_gaps = []
    cycle_logs = []

    for cycle in range(max_depth):
        print(f"{'─'*40}")
        print(f"CYCLE {cycle + 1}/{max_depth}")
        print(f"{'─'*40}")

        if cycle == 0:
            findings, gaps = _investigate_broad(topic)
        else:
            priority_queries, saturation, force_coverage = _analyze_gaps(topic, all_findings, all_gaps)

            if saturation > 80:
                print(f"[Research] Saturation at {saturation}%. Sufficient coverage.")
                break

            if not priority_queries:
                print("[Research] No priority queries generated. Stopping.")
                break

            # Log which thesis forces are thin
            if force_coverage:
                thin_forces = [k for k, v in force_coverage.items() if v < 40]
                if thin_forces:
                    print(f"[Research] Thin coverage on: {', '.join(thin_forces)}")

            findings, gaps = _investigate_targeted(priority_queries)

        all_findings.extend(findings)
        all_gaps.extend(gaps)

        cycle_logs.append({
            "cycle": cycle + 1,
            "findings_added": len(findings),
            "gaps_identified": len(gaps),
            "total_findings": len(all_findings),
        })

        print(f"[Research] Cycle {cycle + 1}: +{len(findings)} findings, {len(gaps)} gaps")
        print(f"[Research] Total accumulated: {len(all_findings)} findings")

        if not autonomous and cycle < max_depth - 1:
            response = input("\n[Research] Continue? (y/n): ").strip().lower()
            if response != 'y':
                break

    # Synthesis
    print(f"\n{'─'*40}")
    print("SYNTHESIS")
    print(f"{'─'*40}")
    synthesis = _synthesize(topic, all_findings)

    # Save
    output = {
        "topic": topic,
        "researched_at": datetime.now().isoformat(),
        "cycles_completed": len(cycle_logs),
        "total_findings": len(all_findings),
        "findings": all_findings,
        "gaps_remaining": all_gaps[-10:] if all_gaps else [],
        "cycle_logs": cycle_logs,
        "synthesis": synthesis,
    }

    output_dir = config.data_dir / "research"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{timestamp}_{_slugify(topic)}.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    md_path = output_dir / f"{timestamp}_{_slugify(topic)}.md"
    md_content = f"# Research: {topic}\n\n"
    md_content += f"*Researched: {datetime.now().strftime('%B %d, %Y')}*\n"
    md_content += f"*Cycles: {len(cycle_logs)} | Findings: {len(all_findings)}*\n\n---\n\n"
    md_content += synthesis
    md_path.write_text(md_content)

    print(f"\n{'='*60}")
    print(f"  Research complete. {len(all_findings)} findings across {len(cycle_logs)} cycles.")
    print(f"  Output: {md_path}")
    print(f"{'='*60}\n")

    return output


# ── Executive Tracking ───────────────────────────────────────────────────

def track_executive(query: str) -> dict:
    """
    Research a specific development executive or company's development hires.
    Builds the dataset of who's been hired into creator-native companies.
    """
    print(f"\n{'='*60}")
    print(f"  CHARLIE — Executive Tracker")
    print(f"  Query: {query}")
    print(f"{'='*60}\n")

    result = call_agent(
        system_prompt=SYSTEM_EXEC_TRACK,
        user_message=f"Research the following executive or company's development hires: {query}",
        tools=[WEB_SEARCH_TOOL],
        model=config.model_daily,
        max_iterations=8,
    )

    parsed = _parse_json(result["text"])

    # Save
    output_dir = config.data_dir / "research" / "executives"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"{timestamp}_{_slugify(query)}.json"

    output = parsed or {"raw_text": result["text"]}
    output["query"] = query
    output["researched_at"] = datetime.now().isoformat()

    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    # Render readable version
    md_path = output_dir / f"{timestamp}_{_slugify(query)}.md"
    md_lines = [f"# Executive Research: {query}\n"]
    md_lines.append(f"*Researched: {datetime.now().strftime('%B %d, %Y')}*\n\n---\n")

    if parsed:
        exec_info = parsed.get("executive", {})
        if exec_info:
            md_lines.append(f"\n## {exec_info.get('name', query)}")
            md_lines.append(f"\n**Title:** {exec_info.get('title', 'Unknown')}")
            md_lines.append(f"\n**Company:** {exec_info.get('company', 'Unknown')}")
            md_lines.append(f"\n**Joined:** {exec_info.get('joined', 'Unknown')}")
            bg = exec_info.get('background', '')
            if bg:
                md_lines.append(f"\n**Background:** {bg}")
            tr = exec_info.get('track_record', '')
            if tr:
                md_lines.append(f"\n**Track Record:** {tr}")

        projects = parsed.get("projects", [])
        if projects:
            md_lines.append("\n\n## Projects\n")
            for p in projects:
                if isinstance(p, dict):
                    md_lines.append(f"- **{p.get('title', '?')}** — {p.get('status', '?')} ({p.get('platform', '?')}). {p.get('reception', '')}")
                else:
                    md_lines.append(f"- {p}")

        related = parsed.get("related_executives", [])
        if related:
            md_lines.append("\n\n## Related Executives\n")
            for r in related:
                if isinstance(r, dict):
                    md_lines.append(f"- **{r.get('name', '?')}** — {r.get('title', '?')} at {r.get('company', '?')}")
                else:
                    md_lines.append(f"- {r}")

        analysis = parsed.get("analysis", "")
        if analysis:
            md_lines.append(f"\n\n## Analysis\n\n{analysis}")
    else:
        md_lines.append(f"\n{result['text']}")

    md_path.write_text("\n".join(md_lines))
    print(f"[ExecTrack] Saved to {md_path}")

    return output


# ── Investigation Functions ──────────────────────────────────────────────

def _investigate_broad(topic: str) -> tuple[list, list]:
    """First-pass broad investigation."""
    print("[Research] Running broad investigation...")

    result = call_agent(
        system_prompt=SYSTEM_INVESTIGATE,
        user_message=f"Research the following topic thoroughly. Prioritize structural analysts (Matthew Ball, Ankler, Puck) and data sources (Parrot Analytics, Nielsen, Edison Research) alongside trade reporting.\n\nTopic: {topic}",
        tools=[WEB_SEARCH_TOOL],
        model=config.model_daily,
        max_iterations=8,
    )

    return _parse_investigation(result["text"])


def _investigate_targeted(queries: list[str]) -> tuple[list, list]:
    """Targeted investigation on specific queries."""
    all_findings = []
    all_gaps = []

    for i, query in enumerate(queries, 1):
        print(f"[Research] Targeted search {i}/{len(queries)}: {query}")

        result = call_agent(
            system_prompt=SYSTEM_INVESTIGATE,
            user_message=f"Search specifically for: {query}\n\nReturn structured findings. Remember to prioritize structural analysts and data sources.",
            tools=[WEB_SEARCH_TOOL],
            model=config.model_daily,
            max_iterations=5,
        )

        findings, gaps = _parse_investigation(result["text"])
        all_findings.extend(findings)
        all_gaps.extend(gaps)

    return all_findings, all_gaps


def _analyze_gaps(topic: str, findings: list, gaps: list) -> tuple[list, int, dict]:
    """Analyze coverage and generate priority queries."""
    print("[Research] Analyzing coverage gaps...")

    findings_summary = json.dumps(findings[-30:], indent=2)
    gaps_summary = json.dumps(gaps[-10:], indent=2)

    result = call_agent(
        system_prompt=SYSTEM_GAP_ANALYSIS,
        user_message=f"""Topic: {topic}

## Findings so far ({len(findings)} total, showing most recent):
```json
{findings_summary}
```

## Gaps identified:
```json
{gaps_summary}
```

Assess coverage across the three thesis forces AND across the IP landscape. Generate priority queries for the next cycle.""",
        model=config.model_daily,
        max_iterations=3,
    )

    analysis = _parse_json(result["text"])
    if not analysis:
        return [], 100, {}

    priority_queries = analysis.get("priority_queries", [])
    saturation = analysis.get("saturation", 50)
    force_coverage = analysis.get("thesis_force_coverage", {})
    coverage = analysis.get("coverage_assessment", "")

    if coverage:
        print(f"[Research] Coverage: {coverage[:200]}")
    print(f"[Research] Saturation: {saturation}%")
    if force_coverage:
        for force, score in force_coverage.items():
            print(f"[Research]   {force}: {score}%")

    return priority_queries, saturation, force_coverage


def _synthesize(topic: str, findings: list) -> str:
    """Synthesize findings into a research document."""
    print(f"[Research] Synthesizing {len(findings)} findings...")

    findings_text = json.dumps(findings, indent=2)

    if len(findings_text) > 50000:
        high_conf = [f for f in findings if f.get("confidence") == "high"]
        med_conf = [f for f in findings if f.get("confidence") == "medium"]
        selected = high_conf + med_conf[:20]
        findings_text = json.dumps(selected, indent=2)
        print(f"[Research] Truncated to {len(selected)} highest-confidence findings")

    result = call_agent(
        system_prompt=SYSTEM_SYNTHESIZE,
        user_message=f"""Synthesize these research findings into a comprehensive document.

Topic: {topic}

## Accumulated Findings
```json
{findings_text}
```

Organize by the three thesis forces. Map the IP landscape. Identify audience migration patterns. Note development executive moves. Write in markdown.""",
        model=config.model_deep,
        max_iterations=3,
    )

    return result["text"]


# ── Signal-to-Research Bridge ────────────────────────────────────────────

def research_from_signal(signal_path: str, signal_index: int):
    """
    Launch research from a pipeline signal — the Brief-to-Thesis bridge.
    """
    with open(signal_path, "r") as f:
        data = json.load(f)

    signals = data.get("signals", [])
    if signal_index >= len(signals):
        print(f"[Research] Signal index {signal_index} out of range ({len(signals)} signals)")
        return

    signal = signals[signal_index]
    headline = signal.get("headline", "Unknown")
    implications = signal.get("forward_implications", [])
    thesis_relevance = signal.get("thesis_relevance", "")

    topic = headline
    if thesis_relevance:
        topic += f" — investigating: {thesis_relevance}"
    if implications:
        topic += f" Key questions: {'; '.join(implications[:3])}"

    print(f"[Research] Investigating signal: {headline}")
    return run_research(topic)


# ── Utilities ────────────────────────────────────────────────────────────

def _parse_investigation(text: str) -> tuple[list, list]:
    parsed = _parse_json(text)
    if parsed:
        findings = parsed.get("findings", [])
        gaps = parsed.get("gaps", [])
        if isinstance(gaps, str):
            gaps = [gaps]
        return findings, gaps
    return [], []


def _parse_json(text: str) -> dict | None:
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    return None


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower().strip())
    return slug[:max_len].strip('_')


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Charlie Research Agent")
    parser.add_argument("topic", nargs="?", help="Research topic or question")
    parser.add_argument("--depth", type=int, default=3, help="Max research cycles (default: 3)")
    parser.add_argument("--interactive", action="store_true", help="Pause between cycles")
    parser.add_argument("--from-signal", type=str, help="Path to signals JSON file")
    parser.add_argument("--signal-index", type=int, default=0, help="Index of signal to investigate")
    parser.add_argument("--track-exec", type=str, help="Track a development executive or company's hires")

    args = parser.parse_args()

    if args.track_exec:
        track_executive(args.track_exec)
    elif args.from_signal:
        research_from_signal(args.from_signal, args.signal_index)
    elif args.topic:
        run_research(args.topic, max_depth=args.depth, autonomous=not args.interactive)
    else:
        print("Usage:")
        print('  python -m agents.research "your research topic"')
        print('  python -m agents.research --track-exec "Aaron Hart Wondery"')
        print('  python -m agents.research --from-signal data/signals/2026-03-28.json --signal-index 4')