# Charlie — Editorial Roadmap v1 (post-revival)

This document specs the next five workstreams for Charlie, sequenced. Unlike the revival build (reliability, DC operator surface, editorial gates, thesis review), these are product improvements measured against Liz's original success test: *she walks into a room already knowing something nobody else has connected yet.* Each workstream is specced to be independently buildable in its own session; do not build more than one per session without an explicit instruction.

**Prerequisites:** the revival build is complete and verified (dead-man's-switch live, editorial gates in the daily pipeline, `/thesis/review` functional). R4 hard-depends on the thesis review workflow. R1–R3 and R5 have no dependency on each other, though R3 degrades gracefully without R1 (noted below).

---

## Standing constraints (every workstream)

1. **Filter bubble firewall.** Liz's interests, slate, sessions, and ratings never steer what Ingestion looks at. Downstream personalization (Tier 3, Companion, the surfaces specced here) is the design; upstream narrowing is the violation. Each workstream below has a firewall note — read it before building.
2. **Agent contract.** New logic follows load state → build prompt → call LLM → persist. Flat-file JSON under `DATA_DIR`, no database.
3. **Adversary isolation and Oven terminality are unchanged.** Nothing here reads adversary feedback at runtime or feeds Oven/Room output back into any agent.
4. **Build complete ≠ verified working.** Every workstream ends with its acceptance criteria actually executed and observed — trigger the run, read the output, click the button.
5. **Models:** `MODEL_DAILY` for ingestion-class work, `MODEL_DEEP` for synthesis-class work. Do not change model strings as part of this roadmap.
6. One commit per workstream, message prefixed `roadmap-R{n}:`.

---

## R1 — The data leg (make the Bullshit Flag check numbers, not quotes)

**Priority: first. This is the unfulfilled core promise of Liz's original spec.**

**Problem.** The Brief's Tier 2 was specced as narrative vs. numbers — streamer claims checked against viewership charts, acquisition narratives against deal-spend rates. Current ingestion is five search passes over trade press, so the "numbers" side of any discrepancy is whatever figure a journalist quoted. Charlie is checking the industry's story against the industry's other stories.

**Build.**

- **New Metrics Ingestion agent**, scheduled weekly (suggest Sunday, after the Saturday thesis, via the existing scheduler loop). Runs on `MODEL_DAILY` with web search. Targets public structured sources: Nielsen weekly streaming top-10s, Parrot Analytics public demand reports, Luminate public charts, quarterly earnings transcripts (extract stated subscriber/content-spend/engagement figures), and publicly reported deal terms.
- **State:** `data/metrics/YYYY-WW.json` per weekly run. Normalized record schema: `{entity, metric, value, unit, as_of_date, source, url, confidence}`. Keep a rolling `data/metrics/index.json` summarizing entities and metrics available, so the Analysis prompt can include a compact inventory rather than raw snapshots.
- **Seed corpus:** convert `streaming_landscape_research.xlsx` (129 shows, six sheets) once into `data/metrics/seed_landscape.json` using the same record schema, tagged `source: "operator_seed_research"`. Write a one-off conversion script; do not hand-transcribe.
- **Analysis agent prompt addition:** when a Tier 2 candidate rests on a quantitative claim, check it against the metrics store. A Bullshit Flag that cites a stored metric against a narrative claim is the target output shape. If the metrics store has nothing relevant, Tier 2 may still fire on narrative-vs-narrative grounds but must say so.

**Firewall note — read carefully.** The seed xlsx and the metrics store enter the system as a *verification reference for Analysis only.* They must NOT be injected into the daily Ingestion agent's prompts as topic guidance, entity lists, or search steering. Same file, two wirings: fact-checking baseline is correct; aperture filter is a firewall violation. If an implementation shortcut would route metrics entities into ingestion search queries, stop and flag instead.

**Acceptance.** Metrics agent runs end-to-end and persists a weekly snapshot; seed conversion produces valid records from all six sheets; a manually triggered daily run produces a brief where the assembled Analysis prompt demonstrably contains the metrics inventory (verify in debug output); at least one Tier 2 item across test runs cites a stored metric with source URL.

---

## R2 — Open Threads (unresolved questions become overnight assignments)

**Priority: second. Cheapest build, reuses everything that exists, and directly inverts the adversary's #1 complaint.**

**Problem.** Every brief tier ends with a "→" question, and Liz's session pushes record what she concluded and what's *still unresolved*. Today, unresolved means dropped — the next brief starts fresh. Meanwhile the top adversary complaint is the validation loop: Charlie re-serving her prior conclusions as new intelligence. The fix for both is the same data used the opposite way: stop re-serving her *conclusions*, start advancing her *open questions*.

**Build.**

- **Nightly pursuit step**, inserted in the daily pipeline before brief generation. Reads the most recent session entry from `context/sessions.json`, extracts items marked unresolved, and for each (cap: 2 per night) runs a research pass on `MODEL_DEEP` with web search attempting to answer or materially advance the question.
- **State:** `data/threads/threads.json` — each thread carries `{question, origin_date, status: open|advanced|resolved|expired, attempts, findings: [{date, summary, sources}]}`. A thread expires after 3 pursuit attempts without material progress, or closes when a later session marks it resolved.
- **Loaf addition:** a compact **Open Threads** section rendered after the three tiers: "You left this unresolved on {date} — here's what came in," 2–3 sentences per thread with source links. Renders only when a thread has new findings; absent otherwise. Section ships in MD/HTML/PDF and (once R5 exists) email.
- **Interaction with editorial gates:** thread findings are Liz-specific downstream content. They are NOT Tier 1/2 candidates, do NOT enter `data/conclusions_log.json`, and the dedup gate does not apply to them. Keep the section visually and structurally distinct from the tiers.

**Firewall note.** Sessions already calibrate Analysis by design — this is the sanctioned downstream direction. The constraint: pursuit runs are a *separate* research step whose output lands only in the threads section. Thread questions must not be appended to the Ingestion agent's search passes.

**Acceptance.** Seed a test session entry with an unresolved item; trigger the nightly run; confirm the thread record persists with findings and the Loaf renders the Open Threads section with working source links; confirm the conclusions log contains nothing from the thread; confirm a session marked resolved closes the thread the following night.

---

## R3 — The Room (pre-meeting counterparty brief)

**Problem.** Sony's contraction changed the function of Liz's first-look deal — material has to arrive more fully formed, and each live conversation (Audiochuck/Shanfield, Pope, future counterparties) carries more weight. Charlie holds 90 days of signals, a thesis, metrics, and Field Work, but it's all organized by day. Nothing assembles what Charlie knows about a *counterparty* at the moment it matters.

**Build.**

- **On-demand surface** modeled on the Oven: a `/room` page (Liz-facing, same auth pattern as Companion/Oven) with a counterparty name field and optional free-text meeting context, backed by `POST /api/room/generate`.
- **Generation pass** on `MODEL_DEEP`: assemble from (a) last 90 days of signals and briefs mentioning the counterparty or its principals, (b) the current thesis, (c) the metrics store (R1) for any quantitative posture, (d) Field Work via `field_access.py` — the gateway and citation caps apply here exactly as on Tier 3; The Room gets no special access. Web search permitted for gap-filling on the counterparty's last 90 days.
- **Output — a one-pager, four fixed sections:** what they've actually done in the window (moves, deals, hires); where they sit relative to the thesis forces; any narrative-vs-data discrepancy in their public posture (cite metrics where available; if R1 isn't built yet, this section runs narrative-only and says so); and one specific question nobody in the room will have thought to ask. Persist to `data/rooms/{slug}-{date}.(json|md|html|pdf)`.
- **Terminal output.** Like the Oven, Room briefs feed nothing — not the conclusions log, not sessions, not any agent.

**Firewall note.** The Room is downstream, Liz-facing synthesis over already-ingested material — sanctioned. The one caution: counterparty names entered here must not be persisted anywhere Ingestion reads (e.g., do not auto-append them to `watching.json`). If Liz wants a counterparty watched, that flows through the Companion's existing explicit flagging.

**Acceptance.** Generate a Room brief for a counterparty known to appear in recent signals (e.g., Audiochuck); confirm all four sections render, Field Work citations respect the caps (check the suppress-and-log path), output persists in all formats, and nothing was written outside `data/rooms/`. Click every button on the page.

---

## R4 — Far Mar: "So What for Liz" (thesis deltas as decisions, not wallpaper)

**Depends on:** revival Phase 4 (`/thesis/review`) live.

**Problem.** The thesis is Charlie's frame, but its updates arrive as industry analysis with no bridge to Liz's actual decisions. The live challenge sitting in the adversary feedback — the Stranger Things ceiling suggesting franchise-scale aggregation is terminal regardless of IP source — is simultaneously a pressure test of Charlie's Discovery Bridge force *and* of Liz's professional positioning (creator-to-scripted translation). A thesis that moves without telling her what the move implies for her slate isn't earning its Saturday slot.

**Build.**

- **Two-pass publish flow.** Pass one is the existing synthesis/refinement — it must run *without* Liz context, exactly as today; the thesis's editorial independence is structural. Pass two runs only at publish time, after thesis content is frozen: a `MODEL_DEEP` annotation pass that reads the published delta (diff vs. prior version) plus `context/profile.json` and `context/slate.json`, and produces a **So What for Liz** section — what changed, and the specific implications for her slate, positioning, and live conversations. Required on every version bump; the publish action fails closed if the section wasn't generated.
- **Render:** the section appears at the top of the Far Mar page for the current version and is archived with each version in `thesis/history/`.
- **Review integration:** on `/thesis/review`, the So What section is generated as a preview at publish time so Liz sees it before confirming publish (it annotates the proposal she's approving; her annotations on thesis *items* still drive refinement passes as specced).

**Firewall note.** The two-pass separation is the whole point: synthesis stays blind to Liz; annotation happens downstream of a frozen thesis. If the implementation ever merges these into one prompt containing both ingested signals and her profile, that's the violation — keep them as two distinct agent invocations with distinct prompts.

**Acceptance.** Run a full thesis cycle: synthesis → review annotations → refinement → publish. Confirm pass one's assembled prompt contains no Liz context (verify in debug output), the So What section generates at publish, publish blocks if generation fails, Far Mar renders it, and `thesis/history/` archives it with the version.

---

## R5 — Delivery (the Loaf comes to her)

**Note on sequencing:** last in this document but independent and cheap — it can be pulled forward into any session if desired. Its leverage is multiplicative: every workstream above only compounds if the daily habit holds, and current evidence (six deeply-engaged days across two months of DC data) says friction is costing engagement.

**Problem.** Liz's original spec asked for a notification that opens directly into the brief. What exists is a URL she has to remember to visit.

**Build.**

- **Email delivery** of the Morning Loaf on successful pipeline completion (fire after the dead-man ping, same "never break the pipeline" try/except discipline). Env-var config: `EMAIL_PROVIDER` (suggest Resend or Postmark — pick one, don't abstract over both), the provider API key, `LOAF_RECIPIENTS` (comma-separated), `EMAIL_FROM`. Unset config → log and skip.
- **Content:** the rendered HTML brief inlined in the email body (email-safe HTML — test in an actual client, not just a preview pane), subject line `The Morning Loaf — {date}: {Tier 1 headline}`, footer link to the live page for the Companion workflow (Discuss / flag / session push stay on-site). Include Open Threads (R2) when present.
- **Thesis notification:** when a new Far Mar version publishes, send a short email: version, one-line summary of the delta, the So What for Liz section (R4) if built, link to the page.
- **Out of scope:** SMS/iMessage, per-recipient preferences, unsubscribe flows. Note them; don't build them.

**Acceptance.** Trigger a manual daily run with a test recipient configured; confirm the email arrives, renders correctly in at least one real client (Gmail), the page link works, and a run with config unset completes cleanly with a skip logged. Publish a test thesis version and confirm the notification fires.

---

## Sequence summary

| # | Workstream | Depends on | Core value |
|---|------------|-----------|------------|
| R1 | Data leg | — | Tier 2 checks claims against numbers, per the original spec |
| R2 | Open Threads | — | Unresolved questions get advanced overnight; inverts the validation loop |
| R3 | The Room | R1 (soft) | Counterparty one-pager for live conversations |
| R4 | So What for Liz | Revival Phase 4 | Thesis deltas translated into slate/positioning implications |
| R5 | Delivery | — (enhanced by R2/R4) | The Loaf arrives instead of waiting; independent, can be pulled forward |

---

*Captured 2026-07-14 during the revival build. Not to be built as part of the revival session; each R-workstream is its own session.*
