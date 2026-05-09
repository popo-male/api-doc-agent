import time
from pathlib import Path

from agents.client import Agent
from agents.action import generate_doc, review_doc, parse_specification
from core.settings import settings
from tools.render import render_final_markdown


def run_agent(raw_content: str, progress_callback=None, api_key: str = None) -> str:
    agent = Agent(api_key)

    # Add progress_callback parameter for frontend
    def log_progress(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    parsed_data = parse_specification(agent, raw_content, log_progress)

    if not parsed_data or "error" in parsed_data:
        error_msg = (
            parsed_data.get("error", "Unknown error")
            if parsed_data
            else "Unknown error"
        )
        return f"Error extracting API data: {error_msg}"

    metadata = parsed_data.get("metadata", {})
    tags = parsed_data.get("tags", {})
    total_endpoints = parsed_data.get("total_endpoints", 0)

    # GUARDRAIL: Max endpoints limit
    if total_endpoints > settings.MAX_ENDPOINTS_PER_RUN:
        log_progress(
            f"Warning: Spec contains {total_endpoints} endpoints. Truncating to {settings.MAX_ENDPOINTS_PER_RUN} to save API limits."
        )

    log_progress("System: successfully extracted endpoints. Beginning documentation...")

    # process endpoints grouped by tags
    grouped_docs = {}
    processed_count = 0

    for tag_name, endpoints in tags.items():
        if processed_count >= settings.MAX_ENDPOINTS_PER_RUN:
            break

        grouped_docs[tag_name] = []

        for endpoint in endpoints:
            if processed_count >= settings.MAX_ENDPOINTS_PER_RUN:
                break

            log_progress(
                f"Worker Agent: documenting {endpoint['method']} {endpoint['path']}"
            )
            doc_chunk = generate_doc(agent, endpoint)
            grouped_docs[tag_name].append(
                {
                    "method": endpoint["method"],
                    "path": endpoint["path"],
                    "markdown": doc_chunk,
                }
            )
            processed_count += 1
            time.sleep(settings.RATE_LIMIT_SLEEP)

    # assembly
    log_progress("System: All endpoints documented! Passing to review...")
    draft_markdown = render_final_markdown(metadata, grouped_docs)

    log_progress("QA Agent: Reviewing final draft for formatting and consistency...")
    final_markdown = review_doc(agent, draft_markdown)

    log_progress("System: Documentation complete and verified!")
    return final_markdown


if __name__ == "__main__":
    try:
        # Resolve path relative to this script location
        wsdl_path = Path(__file__).resolve().parent.parent / "data" / "wsdl.xml"
        with open(wsdl_path, "r") as file:
            wsdl_text = file.read()
    except FileNotFoundError:
        print(f"Error: Cannot find the xml file at {wsdl_path}")
        exit()

    # Run the agent and print the final Markdown
    final_markdown = run_agent(wsdl_text)

    print("\n" + "=" * 50)
    print("FINAL DOCUMENTATION OUTPUT")
    print("=" * 50 + "\n")
    print(final_markdown)
