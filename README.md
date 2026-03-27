# Charlie

An autonomous, multi-agent intelligence system for entertainment industry analysis.

Built for Liz Varner. Operated by Andrew Shipley.

## Architecture

```
charlie/
├── agents/                  # Individual agent modules
│   ├── __init__.py
│   ├── ingestion.py         # Daily source monitoring and signal extraction
│   ├── analysis.py          # Inference chain reasoning and discrepancy detection
│   ├── brief.py             # Three-tier Brief generation
│   └── thesis.py            # Thesis synthesis and update proposals
├── core/                    # Shared infrastructure
│   ├── __init__.py
│   ├── client.py            # Anthropic API client wrapper
│   ├── state.py             # Persistent state management
│   ├── config.py            # Configuration and environment variables
│   └── prompts.py           # System prompt templates
├── data/                    # Persistent state (gitignored except structure)
│   ├── thesis/              # Living thesis document and history
│   ├── signals/             # Accumulated signal objects
│   ├── briefs/              # Generated brief outputs
│   └── watchlists/          # Entities and patterns to monitor
├── context/                 # Liz's persistent context files
│   ├── profile.json         # Professional profile and positioning
│   ├── slate.json           # Active projects and relationships
│   └── watching.json        # What she's tracking vs. background noise
├── orchestrator.py          # Main entry point — coordinates agent execution
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
├── .gitignore
├── Procfile                 # Railway deployment
└── README.md
```

## Agents

- **Ingestion**: Runs daily. Monitors narrative sources (Deadline, Variety, THR, etc.) and data signals. Produces structured signal objects.
- **Analysis**: Takes ingested signals, runs inference chains, detects narrative-vs-data discrepancies. Reasons forward from events to implications.
- **Brief**: Takes ranked findings + Liz's context, produces the three-tier Brief (Signal, Bullshit Flag, Your World).
- **Thesis**: Runs weekly. Accumulates signals, cross-references against current thesis, proposes extensions or revisions.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

## Run

```bash
# Full pipeline
python orchestrator.py

# Individual agents (for testing)
python -m agents.ingestion
python -m agents.analysis
python -m agents.brief
python -m agents.thesis
```

## Deployment

Deployed on Railway with scheduled cron execution.
