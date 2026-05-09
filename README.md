# API Doc Agent

Lightweight Streamlit app and agent workflow that converts Swagger/OpenAPI or WSDL specifications into clean, human-friendly Markdown API documentation using Google Gemini (GenAI) models.

**Highlights:**
- Upload Swagger/OpenAPI (JSON/YAML) or SOAP WSDL (XML) and generate Markdown docs.
- Uses a planner/worker/reviewer agent pattern to parse, document, and polish output.
- Streamlit UI with progress updates and downloadable `.md` output.

**Quick Links**
- App entry: [app.py](app.py)
- Agent workflow: [agents/workflow.py](agents/workflow.py)
- Parser tools: [tools/parser.py](tools/parser.py)
- Render template: [tools/render.py](tools/render.py)
- Configuration loader: [core/config.py](core/config.py)
- Settings (env): [core/settings.py](core/settings.py)

**Requirements**
- Python 3.13+
- See `pyproject.toml` for dependencies (google-genai, jinja2, pydantic-settings, pyyaml, streamlit, zeep).

## Installation

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install the package and dependencies:

```bash
pip install -e .
```

## Configuration

The app reads runtime settings from a `.env` file (via `core/settings.py`) or you can paste your Gemini API key in the Streamlit sidebar.

Create a `.env` with the following keys (do NOT commit secrets):

```
GEMINI_API_KEY=<your_gemini_api_key>
PRIMARY_MODEL_NAME=gemini-3.1-flash-lite
SECONDARY_MODEL_NAME=gemini-2.5-flash

# Optional tuning
MAX_ENDPOINTS_PER_RUN=20
MAX_RETRIES=2
RATE_LIMIT_SLEEP=1
```

Also check [config.yaml](config.yaml) to customize prompt instructions used by the planner/worker/reviewer agents.

## Run the Streamlit App

Start the UI and upload or paste your API specification:

```bash
streamlit run app.py
```

The sidebar lets you supply a Gemini API key (BYOK) if you don't want to store it in `.env`.

## Command-line / Library Usage

You can call the core workflow directly from Python:

```py
from agents.workflow import run_agent

with open('data/swagger.json') as f:
	raw = f.read()

md = run_agent(raw, progress_callback=print, api_key=None)
print(md)
```

## How it Works (high level)

- `tools/parser.py` detects and parses Swagger/OpenAPI or WSDL specs into a normalized endpoint structure.
- `agents/client.py` wraps the Google Gemini client and configures three modes: planner, worker, reviewer.
- `agents/action.py` orchestrates planning (format detection), documentation generation for each endpoint, and QA validation.
- `tools/render.py` assembles the final Markdown using a Jinja2 template.

## File Overview

- [app.py](app.py) — Streamlit frontend
- [agents/](agents) — agent implementations (`client.py`, `action.py`, `workflow.py`)
- [core/](core) — configuration and settings
- [tools/](tools) — parsing and render helpers
- [data/](data) — sample specs used for tests (`swagger.json`, `wsdl.xml`)
- [output/](output) — place to store generated Markdown

## Notes & Best Practices

- Do not commit your `GEMINI_API_KEY` to source control. Use `.env` or the Streamlit BYOK field.
- Monitor and tune `MAX_ENDPOINTS_PER_RUN` to control API consumption and cost.
- For SOAP/WSDL inputs the project uses `zeep` to extract operation signatures.

## Contributing

Contributions are welcome — open issues or PRs for bugs, feature requests, or improved prompts.

## License

This project is provided "as-is". Add a license file if you intend to open-source.
