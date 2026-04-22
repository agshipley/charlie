# Charlie

An autonomous, multi-agent intelligence system for entertainment industry analysis.

Charlie monitors entertainment trade press, structural analysts, and data platforms; runs inference chains on the raw events; produces a daily three-tier editorial ("The Morning Loaf"); critiques its own output with an adversarial second opinion; accumulates signals into a living thesis about the restructuring of entertainment; and lets its reader feed documents ("Field Work") and conversational prompts ("The Oven") back into the pipeline.

Built for Liz Varner. Operated by Andrew Shipley.

---

## Table of contents

1. [What the system does](#what-the-system-does)
2. [Architecture](#architecture)
3. [Repository layout](#repository-layout)
4. [Agents](#agents)
5. [Core modules](#core-modules)
6. [Field Work subsystem](#field-work-subsystem)
7. [The Oven](#the-oven)
8. [Thesis lifecycle](#thesis-lifecycle)
9. [Data model and on-disk layout](#data-model-and-on-disk-layout)
10. [Web application](#web-application)
11. [Scheduling](#scheduling)
12. [Models and API usage](#models-and-api-usage)
13. [Logging and observability](#logging-and-observability)
14. [Environment variables](#environment-variables)
15. [Setup](#setup)
16. [Running the pipeline](#running-the-pipeline)
17. [Deployment (Railway)](#deployment-railway)
18. [Seeding and bootstrapping](#seeding-and-bootstrapping)
19. [Operational notes](#operational-notes)

---

## What the system does

Charlie is a single-reader product. It runs on a daily cadence and produces three artifacts:

1. **The Morning Loaf** — a three-tier editorial brief.
   - **Tier 1 — The Signal**: the highest-implication finding of the day (not the biggest headline).
   - **Tier 2 — The Bullshit Flag**: fires only when a genuine discrepancy exists between a published narrative and the underlying data.
   - **Tier 3 — Your World**: fires only when a signal directly touches Liz's slate, relationships, or active conversations.
2. **Signal Log** — every ingested, structured signal with confidence, weight, thesis-force tag, and source URL.
3. **Adversary Output ("Dark Comprandon")** — an Opus critique of the draft brief along five axes (flattery, pattern exhaustion, inference theater, missing story, comfortable framing). Shadow mode: rendered to file and to a toggle-gated section of the Companion page; never gates the brief.

On a weekly cadence (Saturdays 07:00 PT by default) Charlie runs **Thesis Synthesis** ("Far Mar"): it reviews the last 7 days of signals, cross-references against the current thesis, ingests recent Companion sessions and Field Work, and produces a proposal with extensions, revisions, new patterns, and Field Work engagements. The proposal requires human review before it is applied.

The thesis itself is an opinionated argument about three interlocking forces: **supply exhaustion** (traditional IP pipelines saturating), **demand migration** (audiences pulled to creator platforms by superior algorithmic discovery), and **discovery bridge** (creator-branded content as the mechanism for returning migrated audiences to scripted). Every prompt in the system is anchored in this framework.

---

## Architecture

```
                ┌──────────────────────────────────────────────┐
                │  web.py  (Flask)                             │
                │  ─ Morning Loaf, Companion, Field, Oven      │
                │  ─ Thesis Review (Far Mar)                   │
                │  ─ Run triggers, admin logs                  │
                │  ─ Background scheduler (daily + weekly)     │
                └───────────────┬──────────────────────────────┘
                                │
       ┌────────────────────────┼──────────────────────────────┐
       │                        │                              │
       ▼                        ▼                              ▼
┌─────────────┐         ┌──────────────┐              ┌─────────────────┐
│ orchestrator│         │   agents/    │              │     core/       │
│    .py      │─────────│  ingestion   │              │  client.py      │
│             │         │  analysis    │──────────────│  state.py       │
│ daily /     │         │  brief       │              │  config.py      │
│ thesis /    │         │  adversary   │              │  prompts.py     │
│ --with-field│         │  thesis      │              │  render.py      │
└─────────────┘         │  oven        │              │  logging.py     │
                        │  acknowledge │              │  field_access   │
                        │  research    │              │  field_extract  │
                        └───────┬──────┘              └────────┬────────┘
                                │                              │
                                ▼                              ▼
                        ┌───────────────────────────────────────────┐
                        │    data/  (JSON state on disk)            │
                        │  signals/ briefs/ thesis/ adversary/      │
                        │  field/ oven/ research/ logs/ watchlists/ │
                        └───────────────────────────────────────────┘
```

All agents call the Anthropic API through a single `core.client.call_agent()` loop that handles tool use, `max_tokens` continuation, rate-limit retries, connection errors, and server errors. State is flat JSON on disk — no database. The Flask app both serves the UI and owns the background scheduler thread.

### Pipeline sequence (daily)

```
Ingestion  →  Analysis  →  Brief  →  Adversary  →  Render (MD/HTML/PDF)
 (Sonnet)     (Opus)      (Sonnet)   (Opus)
```

1. **Ingestion** runs five focused web-search passes through a small Sonnet loop, then a single structuring pass distills raw text into signal JSON.
2. **Analysis** loads today's signals, Liz's context, the current thesis, and a 14-day session calibration block; runs inference chains and discrepancy detection on Opus; ranks findings by implication weight.
3. **Brief** selects one finding per tier, retrieves Field Work for the tier-three candidate, enforces citation caps, and produces the three-tier JSON.
4. **Adversary** reloads the brief with 30 days of sessions and 14 days of prior briefs, runs an Opus critique against five failure modes, and saves to `data/adversary/YYYY-MM-DD.json`.
5. **Render** emits markdown, HTML, and PDF versions of the brief (with signal log + adversary shadow section).

### Pipeline sequence (weekly thesis)

```
load_thesis + load_recent_signals(7d) + load_sessions(7d) + Field Work corpus
  →  Opus synthesis  →  proposal JSON
  →  render proposal MD
  →  human review (web)  →  annotate  →  refine (Opus)  →  publish | discard
```

---

## Repository layout

```
charlie/
├── orchestrator.py             # CLI entry point — daily, thesis, manual field paths
├── web.py                      # Flask app: UI, APIs, background scheduler
├── brief_companion.html        # Static companion page (legacy)
├── Procfile                    # Railway web process
├── railway.json                # Railway build/deploy config
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
│
├── agents/                     # One file per agent, each with a run_* entry point
│   ├── ingestion.py            # Daily multi-pass search + structuring
│   ├── analysis.py             # Opus inference chains, discrepancy detection
│   ├── brief.py                # Three-tier editorial generation + Field Work wiring
│   ├── adversary.py            # Opus adversarial critique (shadow mode)
│   ├── thesis.py               # Weekly synthesis + refine + publish
│   ├── acknowledge.py          # First-read response when a Field artifact uploads
│   ├── oven.py                 # On-demand strategic takes
│   └── research.py             # Iterative deep research CLI (ad-hoc)
│
├── core/                       # Shared infrastructure
│   ├── config.py               # Env loading, path roots, directory bootstrap
│   ├── client.py               # Anthropic client wrapper + tool-use agent loop
│   ├── state.py                # StateManager — all JSON read/write + atomic writes
│   ├── prompts.py              # All system-prompt builders (~1000 lines)
│   ├── render.py               # Markdown / HTML / PDF rendering for brief + thesis
│   ├── logging.py              # structlog + stdlib JSON logging configuration
│   ├── field_access.py         # TF-IDF retrieval + citation cap enforcement
│   └── field_extract.py        # Format-aware extractors (.docx/.xlsx/.pdf/.pptx/.md/.txt)
│
├── context/                    # Liz's persistent profile (input to prompts)
│   ├── profile.json            # Role, positioning, strengths, target environments
│   ├── slate.json              # Active projects + key relationships
│   ├── watching.json           # Active vs. background monitoring list
│   └── sessions.json           # Legacy session summaries (weekly, curated)
│
├── seed/                       # First-run seed content copied into data/ on boot
│   ├── sessions.json
│   ├── watchlists/
│   └── adversary/
│
├── data/                       # Persistent state — gitignored for runtime paths
│   ├── signals/                # Daily ingested signals (YYYY-MM-DD.json)
│   ├── briefs/                 # Daily brief output + rendered MD/HTML/PDF
│   ├── adversary/              # Daily adversary output + feedback.json
│   ├── thesis/
│   │   ├── current.json        # The canonical thesis document
│   │   ├── history/            # Timestamped archives of prior thesis versions
│   │   └── proposals/          # Generated proposals awaiting review
│   ├── watchlists/             # default.json — companies/people/patterns
│   ├── field/                  # Field Work subsystem (see below)
│   │   ├── artifacts/          # Metadata records
│   │   ├── originals/          # Raw uploaded files
│   │   ├── extracted/          # Normalized extraction output (JSON)
│   │   ├── acknowledgments/    # Charlie's first-read response JSON
│   │   └── citations.log       # Append-only JSONL citation ledger
│   ├── oven/takes/             # Oven take records
│   ├── research/               # Research agent outputs
│   ├── logs/app.log            # JSON-lines application log
│   ├── sessions.json           # Companion responses (daily)
│   ├── current.json            # ⚠ legacy root-level thesis copy (historical)
│   └── feedback.json           # Signal relevance ratings
│
└── static/js/observability.js  # Client-side error reporter (POSTs to /api/client-error)
```

---

## Agents

All agents share a contract: load state, build a system prompt (from `core/prompts.py`), call `core.client.call_agent()`, parse the JSON response, persist to disk via `StateManager`, and log structured start/complete events.

### `agents/ingestion.py`

**Cadence**: daily. **Model**: `config.model_daily` (Sonnet 4.6 default). **Tools**: Anthropic `web_search_20250305`.

Five independent search passes execute sequentially (each is a fresh `call_agent` loop, `max_uses=3` per search tool, `max_iterations=5`):

1. **Trades scan** — Deadline / Variety / THR.
2. **Creator/audio expansion** — Audiochuck, Wondery, Spotify, iHeartMedia, video-podcast moves.
3. **Watchlist entities** — the first 8 companies from `data/watchlists/default.json`.
4. **IP pipeline and audience data** — viewership, box office, book-to-screen, game adaptations, catalog licensing, ad-tier growth.
5. **Structural analysis** — Matthew Ball, Ankler, Puck, Parrot Analytics.

Each pass returns a concise summary string. Strings are concatenated with `---` separators and fed to a final structuring call (no web search) with the feedback-calibrated structuring prompt. The structuring call extracts a JSON array of signal objects with:

```
headline, source, source_url, signal_type (investment|hiring|departure|deal|
  viewership|mandate_shift|partnership|restructuring|earnings|ip_saturation|
  audience_migration|exec_move|other),
entities, raw_facts, forward_implications,
thesis_force (supply_exhaustion|demand_migration|discovery_bridge|none),
thesis_relevance, confidence (high|medium|low),
implication_weight (1–10), event_date, is_new (bool).
```

Recency rule: only include signals where the underlying event occurred in the last 48 hours, OR where genuinely new data has emerged about an older event.

Output → `data/signals/YYYY-MM-DD.json`.

### `agents/analysis.py`

**Cadence**: daily, chained after ingestion. **Model**: `config.model_deep` (Opus). **Tools**: none.

Loads signals, Liz's context (`profile.json` + `slate.json` + `watching.json`), the current thesis, and a 14-day session calibration block (built from `data/sessions.json` by `get_session_prompt_injection()`). The calibration block separates reinforcing / challenging / new-signal sessions and injects category-level (not entity-level) guidance back into the prompt.

The agent:

1. Runs inference chains on each signal (investment → expansion → team buildout; licensing deal → exclusivity window → competitive response; etc).
2. Detects narrative-vs-data discrepancies.
3. Cross-references signals for pattern convergence (weighted higher when across independent entities).
4. Maps findings to the three thesis forces.
5. Flags IP landscape shifts, audience migration evidence, and development exec moves.
6. Ranks by implication weight and recommends tier placement.

Parse path: `_parse_analysis()` handles `json` code blocks, stitched continuations from `max_tokens` breaks, and raw JSON fallback by brace-matching the outermost object.

Output → returned to the orchestrator, not persisted separately.

### `agents/brief.py`

**Cadence**: daily, chained after analysis. **Model**: `config.model_daily`. **Tools**: none.

Key behavior: before calling the model, the brief agent retrieves Field Work for the highest-weight Tier-3 candidate (`field_access.retrieve_field_work_for_signal(top_k=3)`) and runs the top hit through `field_access.check_citation_caps()`. If the citation is allowed, the Field Work entry (matched spans + relevance score + acknowledgment) is injected into the prompt. If suppressed, the suppression is logged but the brief proceeds without citation. The `record_citation` call only fires after the brief is successfully saved.

The system prompt enforces the editorial rules: never pad; leave a tier null if nothing qualifies; the Signal is the highest-implication finding not the biggest headline; Your World only fires for items touching `slate.json`/`watching.json`.

Output → `data/briefs/YYYY-MM-DD.json` via `state.save_brief()`, plus the rendered MD/HTML/PDF trio from `core.render.render_brief()`.

### `agents/adversary.py`

**Cadence**: daily, between brief and render. **Model**: `config.model_deep` (Opus). **Tools**: none.

Shadow mode: the adversary's output is written to `data/adversary/YYYY-MM-DD.json` and rendered into the MD/HTML/PDF brief + the toggleable "Dark Comprandon" section on the Companion page. It never changes the brief itself and never blocks the pipeline — any exception returns a `null_finding` record so downstream rendering always has a shape to work with.

The adversary loads 30 days of sessions, 14 days of prior briefs, and the full Field Work corpus, then critiques along five axes:

| Axis | What it flags |
|---|---|
| `flattery` | Brief says what prior sessions said Liz wanted to hear |
| `pattern_exhaustion` | A pattern has been cited N× in a rolling window — diminishing returns |
| `inference_theater` | The inference chain doesn't actually follow from the underlying signal |
| `missing_story` | The signal supported a bigger read that the brief declined |
| `comfortable_framing` | Phrases that make strategic uncertainty sound confident |

Each finding can reference a Field Work `artifact_id`; those references are logged as `field_adversary_pressure` events.

### `agents/thesis.py`

**Cadence**: weekly (Saturday 07:00 PT by default). **Model**: `config.model_deep` (Opus). **Tools**: none.

Synthesizes the last 7 days of signals + sessions + the entire Field Work corpus against the current thesis. Emits a proposal with:

- `extensions` — new claims, each with `force`, `confidence`, and evidence signal IDs.
- `revisions` — edits to existing thesis claims (targeted by `claim_id`).
- `new_patterns` — emerging patterns across multiple signals.
- `field_work_engagements` — explicit treatment of Field Work documents (agree / extend / challenge / acknowledge-gap).
- `summary` — one-paragraph description.

The proposal is saved to `data/thesis/proposals/YYYY-MM-DD.json` with review metadata (`iteration`, `max_iterations`, `status: "pending"`, `history`). Two further entry points handle the review cycle:

- `refine_proposal(proposal, thesis)` — loads Liz's per-item flags (`accept` / `needs_revision` / `reject`) and free-text annotations, runs an Opus refinement pass that preserves item IDs and increments `iteration`.
- `publish_proposal(proposal)` — applies non-rejected items to `current.json`, bumps the thesis `version`, archives the prior version into `data/thesis/history/`.

### `agents/acknowledge.py`

**Triggered by**: a Field Work artifact upload. **Model**: Opus, `max_iterations=1`, no tool use.

When a user uploads a document, the web layer runs extraction (`core.field_extract.extract_artifact`), then calls `run_acknowledge(artifact)`. The agent produces a five-section structured response:

1. `what_i_read_this_to_be_arguing` — Charlie's plain-language read.
2. `frameworks_extracted` — named frameworks Liz coined in the document (used as a retrieval boost signal downstream).
3. `empirical_foundation` — what's evidenced vs. asserted.
4. `connections_to_current_thesis` — explicit mapping to thesis forces or claims.
5. `open_questions` — what Charlie wants to test next.

Failure modes save a minimal `failed: true` placeholder so the UI can offer a retry affordance. Output → `data/field/acknowledgments/{artifact_id}.json` (atomic write).

### `agents/oven.py`

**Triggered by**: `POST /api/oven/generate`. **Model**: Opus.

Generates a strategic "take" from a user prompt, grounded in the current thesis, the last 14 days of briefs, all Field Work (with extracted content + acknowledgments inline), `context/` files, and the last 7 days of sessions. Output shape:

```
situation, whats_on_their_mind, worth_raising[], watch_for[], open_loops[]
```

Saved to `data/oven/takes/{take_id}.json` and available via `/oven/{take_id}` (HTML), `/oven/{take_id}/download` (markdown), or the Oven index.

### `agents/research.py`

Ad-hoc iterative research CLI. Not part of the daily or weekly pipeline. Runs broad → gap-analysis → targeted cycles (max N), synthesizes into markdown. Includes a `track_executive` mode for building the development-exec dataset at creator-native companies.

---

## Core modules

### `core/config.py`

Centralized configuration dataclass. On import it:

1. Loads `.env` via `python-dotenv`.
2. Validates `ANTHROPIC_API_KEY`.
3. Resolves `model_daily`, `model_deep`, `brief_hour`, `brief_timezone`, `data_dir`, `context_dir`.
4. Creates every subdirectory Charlie writes to: `signals`, `briefs`, `thesis`, `thesis/history`, `watchlists`, `adversary`, `logs`, `field`, `field/artifacts`, `field/originals`, `field/extracted`, `field/acknowledgments`, `oven/takes`.

Exposes `config` as a module-level singleton. Property accessors (`config.signals_dir`, `config.briefs_dir`, `config.thesis_dir`, `config.field_dir`, `config.oven_dir`) return `Path` objects.

### `core/client.py`

Thin Anthropic wrapper around `anthropic.Anthropic()` with a 5-minute per-request timeout. `call_agent()` implements the full tool-use loop:

- Iterates up to `max_iterations` (default 20) API calls.
- On `stop_reason="end_turn"` — collects text and exits.
- On `stop_reason="max_tokens"` — appends a user continuation message asking the model to resume exactly where it left off.
- On `stop_reason="tool_use"` — dispatches each tool block through `tool_handlers` (user-supplied dict). `web_search` is server-side and needs no handler.
- `_call_with_retry()` handles `RateLimitError` (30s × attempt), `APIConnectionError` (10s × attempt), and 5xx `APIStatusError` (15s × attempt), up to 5 retries.

Every iteration logs a timestamped `[HH:MM:SS]` progress line. Returns `{text, messages, tool_results}`.

### `core/state.py`

`StateManager` — the single owner of disk writes. Every persistence path in the system routes through here. Atomic write semantics for Field Work and Oven (`_atomic_write_json`: write to `.tmp`, fsync, `os.replace`); non-atomic for signals, briefs, thesis, sessions. Every write emits `state_write_attempt` / `state_write_success` / `state_write_failed` log events for observability.

Public surface:

- Signals: `save_signals`, `load_signals`, `load_recent_signals(days)`.
- Briefs: `save_brief`, `load_brief`, `load_recent_briefs(days)`.
- Thesis: `load_thesis`, `save_thesis` (with history archive), `save_thesis_proposal`, `load_latest_proposal`, `save_proposal_update`.
- Watchlists: `load_watchlist`, `save_watchlist`.
- Sessions: `load_sessions(days_back)`, `append_session`.
- Adversary: `save_adversary`, `load_adversary`, `save_adversary_feedback`, `load_adversary_feedback`.
- Field Work: `save_field_artifact`, `load_field_artifact`, `delete_field_artifact`, `list_field_artifacts`, `save_field_extracted`, `load_field_extracted`, `load_field_acknowledgment`.
- Oven: `save_take`, `load_take`, `list_takes`, `delete_take`.
- Context: `load_context()` — loads all four of `context/*.json` into a dict.

### `core/prompts.py`

All system-prompt builders (~1000 lines). Key exported functions:

- `build_ingestion_prompt(watchlist, thesis_summary)` — structuring prompt for the ingestion agent.
- `build_analysis_prompt(context, thesis)` — Opus analysis prompt with Liz's context, current thesis claims, and the thesis forces block.
- `build_brief_prompt(context, field_work_context=None)` — tier-generation rules, session context, optional Field Work block.
- `build_adversary_prompt(brief, sessions, briefs, field_work=None)` — returns `(system_prompt, user_message)`.
- `build_thesis_prompt(thesis, recent_signals, field_work=None)` — thesis synthesis with structured output schema.
- `build_oven_prompt(user_prompt, thesis, recent_briefs, field_artifacts, context, recent_sessions)` — returns `(system_prompt, user_message)`.
- `build_acknowledge_prompt(artifact, extracted, thesis)` — returns `(system_prompt, user_message)`.
- Shared framework blocks: `THESIS_FORCES`, `SOURCE_PRIORITY`, `load_sessions_context()`.

### `core/render.py`

Produces human-readable artifacts from pipeline JSON.

- `render_brief(brief, signals, findings, run_date, adversary)` → writes MD + HTML + PDF (PDF via `weasyprint` subprocess or Chrome headless fallback).
- `render_thesis_proposal(proposal)` → writes MD for review.

The HTML template uses a newspaper/Georgia-serif aesthetic with a shadow-mode adversary section styled in Courier, rendered inline at the bottom of the brief.

### `core/logging.py`

Configures `structlog` once per process. Emits JSON logs to both `stderr` (captured by Railway) and `data/logs/app.log`. Log level via `LOG_LEVEL` env var, default INFO. Silences `werkzeug`/`anthropic`/`httpx`/`httpcore` chatter to WARNING. Exposes `get_logger(name)` and `error_context(exc)`.

### `core/field_access.py`

Field Work retrieval layer (see below) — the only module other agents should import when they need Field Work content. Handles TF-IDF scoring (sklearn if available, hand-rolled fallback otherwise), heading boosts, framework-term bonuses, matched-span extraction, per-tier and per-artifact citation caps, and the append-only `citations.log` ledger.

### `core/field_extract.py`

Dispatches uploaded files to format-specific extractors:

- `.docx` — `python-docx`, walks the body, distinguishes headings via Word style names, captures tables.
- `.xlsx` — `openpyxl`, one section per sheet, captures headers + rows.
- `.pdf` — `pdfplumber` with a PyMuPDF (`fitz`) fallback for browser-print PDFs; font-size-based heading detection (>= 1.25× median).
- `.pptx` — `python-pptx`, one section per slide, first text box = slide title.
- `.md` — regex-based heading parse.
- `.txt` — plain read.

Normalized output schema: `{artifact_id, extracted_at, source_format, title_extracted, sections[{heading, level, content}], tables[], full_text, word_count, extraction_notes[]}`. Written atomically to `data/field/extracted/{artifact_id}.json`.

---

## Field Work subsystem

Field Work is the mechanism by which Liz feeds first-party documents (pitch decks, industry analyses, memos, books) into Charlie's editorial state without polluting the web-search signal.

### Upload flow

```
POST /api/field/upload (multipart)
    → save original to data/field/originals/{id}.{ext}
    → save metadata to data/field/artifacts/{id}.json
    → field_extract.extract_artifact()  → data/field/extracted/{id}.json
    → run_acknowledge(artifact)  → data/field/acknowledgments/{id}.json
    → redirect to /field/work/{id}
```

Uploads are capped at 25 MB. Supported extensions are the six above. The acknowledge call is the heavy step — Opus single-shot, no tools — and is typically backgrounded.

### Retrieval

Three entry points on `core.field_access`:

| Function | Used by | Behavior |
|---|---|---|
| `retrieve_field_work_for_signal(signal, top_k=3)` | Brief (tier-3) | TF-IDF rank against the signal's headline + entities + raw_facts + forward_implications. Heading overlap 20% weight. Framework-term match +0.05 bonus. Returns top_k with `{artifact, extracted, acknowledgment, relevance_score, matched_spans}`. |
| `retrieve_field_work_for_thesis_synthesis()` | Thesis | Entire corpus, no filtering. |
| `retrieve_field_work_for_adversary()` | Adversary | Entire corpus, no filtering. |

### Citation caps

To prevent the brief from becoming a Field Work recycler, `check_citation_caps(artifact_id, relevance_score, today)` enforces:

- Per-artifact: any artifact can be cited at most `FIELD_CAP_PER_ARTIFACT` (default 2) times in a rolling 14-day window.
- Weak tier (0.70–0.79): `FIELD_CAP_WEAK` (default 2) citations in any 7-day window.
- Medium tier (0.80–0.89): `FIELD_CAP_MED` (default 4) in any 7-day window.
- Strong tier (0.90+): `FIELD_CAP_STRONG` (default 6) in any 7-day window.
- Below 0.70: never cited.

All four caps are overridable via env vars. Decisions are written to `data/field/citations.log` as JSONL (`event=citation`) and suppressed attempts are logged at WARN level.

### Acknowledgments

Every artifact has an acknowledgment with the five required sections. The UI at `/field/work/{id}` shows the acknowledgment alongside the extracted text; `/api/field/work/{id}/reacknowledge` re-runs the agent. Acknowledgments are deliberately not fed through Liz's context files — Charlie must read the document itself, not secondhand.

---

## The Oven

On-demand strategic synthesis. A user submits a free-form prompt ("how should I think about Audiochuck's Chernin raise given the romantasy saturation signals?") via `POST /api/oven/generate`. The Oven agent loads the full context stack and returns a structured take.

### Output schema

```
situation           : string — what's going on, in Liz's voice
whats_on_their_mind : string — the implied counterparty's POV
worth_raising       : array  — conversation moves
watch_for           : array  — what to monitor
open_loops          : array  — unresolved questions
```

Takes are saved to `data/oven/takes/{take_id}.json`, listed at `/oven`, viewed at `/oven/{take_id}`, and downloadable as markdown at `/oven/{take_id}/download`.

---

## Thesis lifecycle

1. **Synthesis** — `run_thesis(days_back=7)` writes a pending proposal.
2. **Review surface** — `/thesis/review` renders the proposal with per-item flag buttons (`accept` / `needs_revision` / `reject`) and an annotation textarea. The nav bar surfaces a "Review ●" link when a pending proposal exists (handled by `nav_html()` in `web.py`).
3. **Annotate** — `POST /api/thesis/annotate` writes flags + annotations back to the proposal JSON via `state.save_proposal_update()`.
4. **Refine** — `POST /api/thesis/refine` calls `refine_proposal()` which invokes Opus to apply the annotations, increments `iteration`, appends to `history`.
5. **Publish** — `POST /api/thesis/publish` calls `publish_proposal()` which applies non-rejected items to `current.json`, archives the prior version to `data/thesis/history/{timestamp}.json`, and bumps `version`.
6. **Discard** — `POST /api/thesis/discard` marks the proposal status without applying it.

The proposal's `max_iterations` defaults to 5 to bound refinement loops.

---

## Data model and on-disk layout

All persistent state lives in `data/`. Paths are defined by `core/config.py`. The `.gitignore` excludes daily-generated content (`data/signals/*.json`, `data/briefs/*.json`, `data/thesis/history/`) but tracks seed content.

### Key file shapes

**`data/signals/YYYY-MM-DD.json`**
```
{ "date": "...", "extracted_at": "...", "signals": [ {headline, signal_type, entities, raw_facts, forward_implications, thesis_force, confidence, implication_weight, event_date, is_new, ...}, ... ] }
```

**`data/briefs/YYYY-MM-DD.json`**
```
{ "date": "...", "generated_at": "...", "brief": { "tier_1": {headline, body, open_question} | null, "tier_2": ... | null, "tier_3": ... | null } }
```

**`data/thesis/current.json`**
```
{ "core_argument": "...", "updated_at": "...", "version": int,
  "forces": { "supply_exhaustion": {summary, evidence[], confidence, gaps[]}, "demand_migration": {...}, "discovery_bridge": {...} },
  "claims": [...] }
```

**`data/thesis/proposals/YYYY-MM-DD.json`**
```
{ "generated_at": "...", "iteration": 0, "max_iterations": 5, "status": "pending",
  "summary": "...", "extensions": [...], "revisions": [...], "new_patterns": [...],
  "field_work_engagements": [...], "history": [{iteration, type, timestamp, ...}] }
```

**`data/adversary/YYYY-MM-DD.json`**
```
{ "run_date": "...", "brief_date": "...", "null_finding": bool,
  "summary": str | null,
  "findings": { "flattery": [...], "pattern_exhaustion": [...], "inference_theater": [...],
                "missing_story": [...], "comfortable_framing": [...] } }
```

**`data/field/artifacts/{id}.json`**
```
{ "id": "...", "filename": "...", "stored_filename": "...", "uploaded_at": "...",
  "source_format": "...", "status": "extracted" | "failed", ... }
```

**`data/field/citations.log`** (JSONL)
```
{"event":"citation","artifact_id":"...","brief_date":"...","signal_id":"...","relevance_score":0.87}
```

**`data/sessions.json`**
```
{ "sessions": [ { "id", "brief_date", "tier", "question", "disposition", "thesis_force", "signal_category", "insight", "confidence", "submitted_at" }, ... ] }
```

---

## Web application

`web.py` is a single-file Flask app (~3300 lines) that serves all UI and API. Routes:

### Pages

| Route | Template | Purpose |
|---|---|---|
| `/` | `BRIEF_TEMPLATE` | Today's Morning Loaf + Signal Log + Adversary shadow |
| `/brief/<date>` | same | A historical brief |
| `/companion` | `COMPANION_TEMPLATE` | Daily tier-response form + Dark Comprandon toggle |
| `/archive` | `ARCHIVE_TEMPLATE` | All prior briefs |
| `/thesis` | thesis view | Current thesis document |
| `/thesis/review` | review view | Pending proposal with annotation UI |
| `/field` | field index | Upload + list artifacts |
| `/field/work/<id>` | artifact view | Acknowledgment + extracted text |
| `/oven` | oven index | Take list + new-take form |
| `/oven/<id>` | take view | Single take |
| `/oven/<id>/download` | — | Markdown download of a take |
| `/run` | `RUN_TEMPLATE` | Manual pipeline triggers |
| `/book` | book view | Companion book / long-form document |
| `/admin/logs?token=…` | log viewer | JSON log viewer, token-gated via `ADMIN_TOKEN` |
| `/seed` | — | Force-re-copy `seed/` into `data/` |

### APIs

| Route | Method | Purpose |
|---|---|---|
| `/api/feedback` | POST | Per-signal relevance rating (1–10) |
| `/api/feedback/summary` | GET | Aggregate rating summary by signal_type |
| `/api/companion/session` | POST | Write a session entry to `data/sessions.json` |
| `/api/adversary/feedback` | POST | Per-finding fair-hit / off-base / partially-right + note |
| `/api/brief/<date>` | GET | Brief JSON |
| `/api/thesis/annotate` | POST | Flags + annotations on proposal items |
| `/api/thesis/refine` | POST | Kick off refinement pass |
| `/api/thesis/publish` | POST | Apply proposal to `current.json` |
| `/api/thesis/discard` | POST | Mark proposal discarded |
| `/api/field/upload` | POST | Multipart upload, kicks off extract + acknowledge |
| `/api/field/<id>` | DELETE | Remove artifact, original, extracted, acknowledgment |
| `/api/field/work/<id>/reacknowledge` | POST | Re-run acknowledge (backgrounded) |
| `/api/field/work/<id>/status` | GET | Poll status while backgrounded job runs |
| `/field/originals/<id>` | GET | Download original file |
| `/api/oven/generate` | POST | Kick off take generation |
| `/api/oven/<id>` | DELETE | Delete a take |
| `/api/client-error` | POST | Browser-side error reporter (rate-limited 50/5min/key) |

### Shared UI primitives

- `nav_html(active)` — renders the top nav; dynamically surfaces a "Review ●" link only when a pending proposal exists.
- `SHARED_STYLES` — a single CSS block injected into every template.
- `static/js/observability.js` — a stub loaded in every template that captures window errors and POSTs to `/api/client-error` for server-side logging.

### Feedback injection

`get_feedback_prompt_injection()` (defined in `web.py`, imported by `agents.ingestion`) builds a calibration block from `data/feedback.json` that biases the structuring pass toward signal types the reader rates highly.

---

## Scheduling

Two independent schedulers coexist:

1. **In-process scheduler in `web.py`** — `start_scheduler()` launches a daemon thread that sleeps 5 minutes between checks. It triggers:
   - Daily pipeline the first time local time crosses `BRIEF_HOUR` (default 06:00) each day.
   - Thesis pipeline the first time local time crosses `BRIEF_HOUR + 1` on `THESIS_DAY` (0=Monday, 5=Saturday default) each week.
   - Local time computation uses a fixed `-7h` UTC offset (PDT-equivalent operator tool precision, not DST-correct).
2. **Orchestrator CLI** — `python orchestrator.py [--full|--thesis|--brief|--adversary] [--with-field] [--thesis-days N] [--date YYYY-MM-DD] [--test]`.

The CLI and scheduler share state, so a manual run during the scheduler window will not double-fire (the scheduler tracks `last_brief_date` and `last_thesis_date`).

### Manual pipelines

| Command | Effect |
|---|---|
| `python orchestrator.py` | Daily pipeline (ingest → analyze → brief → adversary → render) |
| `python orchestrator.py --full` | Daily + thesis synthesis |
| `python orchestrator.py --thesis` | Thesis synthesis only |
| `python orchestrator.py --brief` | Re-run today's brief against saved signals |
| `python orchestrator.py --adversary` | Re-run adversary against today's brief |
| `python orchestrator.py --thesis --with-field` | Thesis synthesis with Field Work wiring (confirm prompt) |
| `python orchestrator.py --brief --with-field` | Re-run brief with Field Work (confirm prompt) |
| `python orchestrator.py --adversary --with-field` | Re-run adversary with Field Work (confirm prompt) |
| `python orchestrator.py --test` | Dry-run — prints config and exits |
| `python orchestrator.py --date 2026-04-15 --brief` | Re-run for a specific historical date |

---

## Models and API usage

Model selection is centralized in `core/config.py` and resolved per call:

```
MODEL_DAILY  default: claude-sonnet-4-6  — ingestion search, ingestion structuring, brief
MODEL_DEEP   default: claude-opus-4-6    — analysis, adversary, thesis, oven, acknowledge
```

All agents go through `core.client.call_agent()`, which handles:

- 5-minute per-request timeout.
- Tool-use loop with explicit `tool_handlers` dispatch.
- `max_tokens` continuation — the agent is asked to resume mid-response rather than restart.
- Retry policy — 5 attempts for `RateLimitError`, `APIConnectionError`, and 5xx `APIStatusError` with escalating backoffs; 4xx raises immediately.
- Timestamped console progress per iteration.

Tool use: the only tool the system exposes is Anthropic's server-side `web_search_20250305` (used by ingestion and research). Everything else is direct messages + JSON-schema discipline in the system prompt.

---

## Logging and observability

- **Framework**: `structlog` on top of stdlib `logging`, JSON renderer, UTC ISO timestamps.
- **Sinks**: `stderr` (captured by Railway logs) + `data/logs/app.log`.
- **Level**: `LOG_LEVEL` env var, default INFO. Third-party loggers (`werkzeug`, `anthropic`, `httpx`, `httpcore`) forced to WARNING.
- **Log viewer**: `/admin/logs?token=<ADMIN_TOKEN>` renders the tail of `app.log` with `level` / `logger` query-string filters.
- **Key event names**: `agent_start`, `agent_complete`, `agent_failed`, `state_write_attempt`, `state_write_success`, `state_write_failed`, `state_delete_success`, `field_retrieval_called`, `field_citation_considered`, `field_citation_allowed`, `field_citation_suppressed`, `field_adversary_pressure`, `field_thesis_engagement`, `request_received`, `request_completed`, `pipeline_triggered`, `thesis_synthesis_triggered`, `client_error`.
- **Client errors**: `static/js/observability.js` on every page catches `window.onerror` and unhandled promise rejections and POSTs to `/api/client-error`. Rate-limited per `(source, lineno, colno)` to 50 reports per 5 minutes.

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API credential |
| `MODEL_DAILY` | | `claude-sonnet-4-6` | Model for ingestion + brief |
| `MODEL_DEEP` | | `claude-opus-4-6` | Model for analysis + adversary + thesis + oven + acknowledge |
| `BRIEF_HOUR` | | `6` | Local hour (24h) for the daily brief trigger |
| `THESIS_DAY` | | `5` (Saturday) | Weekday (0=Mon) for thesis synthesis |
| `BRIEF_TIMEZONE` | | `America/Los_Angeles` | Informational label; scheduler uses fixed −7h offset |
| `DATA_DIR` | | `data` | Path (relative to project root) for persistent state |
| `LOG_LEVEL` | | `INFO` | Log verbosity |
| `ADMIN_TOKEN` | | unset | Token required for `/admin/logs`; unset = disabled |
| `FIELD_CAP_WEAK` | | `2` | Max weak-tier (0.70–0.79) Field Work citations per 7 days |
| `FIELD_CAP_MED` | | `4` | Max medium-tier (0.80–0.89) citations per 7 days |
| `FIELD_CAP_STRONG` | | `6` | Max strong-tier (0.90+) citations per 7 days |
| `FIELD_CAP_PER_ARTIFACT` | | `2` | Max citations of any single artifact per 14 days |
| `PORT` | | `5001` | Flask bind port (overridden by Railway) |

---

## Setup

```bash
git clone https://github.com/agshipley/charlie.git
cd charlie
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — at minimum set ANTHROPIC_API_KEY
```

### Python dependencies

```
anthropic>=0.45.0        # API client
python-dotenv>=1.0.0     # .env loading
flask>=3.0.0             # web + API
structlog>=24.0.0        # JSON logging
python-docx>=1.1.0       # .docx extraction
openpyxl>=3.1.0          # .xlsx extraction
pdfplumber>=0.11.0       # .pdf extraction (primary)
pymupdf>=1.24.0          # .pdf extraction (fallback)
python-pptx>=1.0.0       # .pptx extraction
scikit-learn>=1.4.0      # TF-IDF for Field Work retrieval (optional; hand-rolled fallback exists)
```

System dependency for PDF rendering: either `weasyprint` installed into the venv or Chrome/Chromium available on `PATH` for headless fallback. The brief and thesis will still produce MD and HTML if the PDF pass fails.

---

## Running the pipeline

### Full daily pipeline

```bash
python orchestrator.py
```

Takes roughly 8–12 minutes end-to-end: ingestion ~5–6 min (five web-search passes), analysis ~1–2 min, brief ~1 min, adversary ~1–2 min, render ~5–15 sec.

### Weekly thesis synthesis

```bash
python orchestrator.py --thesis
```

Takes 4–6 minutes on Opus. The result is a pending proposal at `data/thesis/proposals/YYYY-MM-DD.json`; review at `/thesis/review`.

### Web server (local dev)

```bash
python web.py
# → http://localhost:5001
```

The server spawns the scheduler thread on boot. The first scheduler check is immediate; subsequent checks every 5 minutes.

### Individual agents (debugging)

```bash
python -m agents.ingestion
python -m agents.analysis
python -m agents.brief
python -m agents.adversary
python -m agents.thesis
python -m agents.research "How are podcast companies structuring TV/film divisions?"
python -m agents.research --track-exec "Matt Shanfield Audiochuck"
```

---

## Deployment (Railway)

```
Procfile:      web: python web.py
railway.json:  builder = NIXPACKS
               startCommand = python web.py
               healthcheckPath = /
               restartPolicyType = ON_FAILURE
```

`web.py` binds to `PORT` (Railway-injected) and spawns the in-process scheduler thread. Persistent state lives on Railway's volume at `/app/data` (mounted over `data/` in the repo). Seed content in `seed/` is copied into the data volume on first boot by `seed_data()`.

Logs stream via `stderr` to Railway's log viewer. The operator can also read the local tail via `/admin/logs?token=<ADMIN_TOKEN>` once `ADMIN_TOKEN` is set.

---

## Seeding and bootstrapping

On first boot, `seed_data()` copies every file under `seed/` into `data/` (non-destructive — only copies if the destination doesn't exist). This bootstraps the watchlist, an initial sessions history, and any adversary seed content without baking runtime state into the repo.

Force a re-seed by hitting `/seed` in the browser (uses the same logic but overwrites unconditionally).

---

## Operational notes

- **Single-user semantics.** The "reader" is a specific person. `context/profile.json`, `context/slate.json`, and `context/watching.json` are the prompts' central grounding; replacing them effectively retargets the whole system.
- **No database.** JSON files + atomic writes are the contract. `StateManager` is the single gate. Bulk migrations happen by editing JSON directly.
- **Idempotency.** Re-running the daily pipeline for a given date overwrites that day's signals / brief / adversary outputs. The `--with-field` variants prompt for confirmation before overwriting.
- **Recency discipline.** Ingestion is tuned toward the last 48 hours. The analysis prompt explicitly rejects "recycled old news with new framing"; the adversary's `pattern_exhaustion` axis checks for overused frames in the recent brief history.
- **Shadow mode.** The adversary's output is informational, not editorial — it never changes what the brief says. Feedback on adversary findings is collected (`/api/adversary/feedback`) but does not feed back into the brief pipeline automatically.
- **Thesis authority.** Only the thesis-review flow (annotate → refine → publish) changes `current.json`. The weekly synthesis job never writes the thesis directly.
- **Field Work hygiene.** Uploaded documents are first-party inputs. They are not searched on the web, not summarized into context files, and not cited without passing the relevance threshold and rate caps. The acknowledge agent is the only component that reads an artifact end-to-end; other agents read excerpts retrieved by `field_access`.
