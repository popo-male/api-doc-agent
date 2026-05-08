import json
import sys
import time
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from core.config import config
from core.settings import settings
from tools.parser_tools import (
    parse_swagger,
    parse_swagger_tool,
    parse_wsdl,
    parse_wsdl_tool,
)
from tools.render_tools import render_final_markdown

client = genai.Client(api_key=settings.GEMINI_API_KEY)

planner_config = types.GenerateContentConfig(
    tools=[parse_swagger_tool, parse_wsdl_tool],
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowed_function_names=["parse_swagger", "parse_wsdl"],
        )
    ),
    system_instruction=config.model.instruction.planner,
    temperature=0.0,  # We want the planner to be deterministic
)

worker_config = types.GenerateContentConfig(
    system_instruction=config.model.instruction.worker, temperature=0.1
)

reviewer_config = types.GenerateContentConfig(
    system_instruction=config.model.instruction.reviewer,
    temperature=0.0,
)


def generate_endpoint_doc(endpoint_data: dict, attempt=1) -> str:
    prompt = f"Please document this specific endpoint:\n{json.dumps(endpoint_data, indent=2)}"

    try:
        response = client.models.generate_content(
            model=settings.PRIMARY_MODEL_NAME, contents=prompt, config=worker_config
        )
        doc = response.text

        if not validate_endpoint_doc(doc, endpoint_data):
            print("Hallucination detected! Parameters don't match spec.")
            if attempt <= settings.MAX_RETRIES:
                print(f"Retrying... Attempt {attempt}/{settings.MAX_RETRIES}")
                return generate_endpoint_doc(endpoint_data, attempt + 1)
            else:
                print("Max retries reached.")
                return f"### {endpoint_data['method']} {endpoint_data['path']}\n*Error: Failed to generate accurate documentation after {settings.MAX_RETRIES} attempts.*"
        return doc
    except genai_errors.ServerError as exc:
        return f"## {endpoint_data['method']} {endpoint_data['path']}\n\nError generating documentation: {exc}"
    except Exception as exc:
        return f"### {endpoint_data['method']} {endpoint_data['path']}\n*Error: Documentation generation failed due to API connection issues.*"


def validate_endpoint_doc(doc_text: str, endpoint_data: dict) -> bool:
    """GUARDRAIL: Checks for hallucinated parameters."""
    valid_params = [
        p.get("name", "").lower()
        for p in endpoint_data.get("parameters", [])
        if isinstance(p, dict)
    ]

    # Dynamically build the list of allowed parameter names
    for p in endpoint_data.get("parameters", []):
        if isinstance(p, dict):
            #  Add the root parameter name
            base_name = p.get("name", "").lower()
            if base_name:
                valid_params.append(base_name)

            #  If it has a schema, add all the inner properties to the allowed list
            schema = p.get("schema", {})
            if isinstance(schema, dict):
                # case A: standard object payload
                if "properties" in schema:
                    for prop_name in schema["properties"].keys():
                        valid_params.append(prop_name.lower())
                # case B: array of objects payload
                elif schema.get("type") == "array" and "items" in schema:
                    items = schema["items"]
                    if isinstance(items, dict) and "properties" in items:
                        for prop_name in items["properties"].keys():
                            valid_params.append(prop_name.lower())

    param_section = (
        doc_text.split("#### Request Parameters")[-1]
        .split("#### Request Payload")[0]
        .strip()
    )

    lines = [
        line.strip()
        for line in param_section.split("\n")
        if line.strip().startswith("|")
    ]

    # If there are no real parameters in the spec...
    if not valid_params:
        # Check if the LLM built a table with actual data rows (more than 2 lines = header + divider + data)
        if len(lines) > 2:
            data_row = lines[2].lower()
            if (
                "none" not in data_row
                and "n/a" not in data_row
                and "empty" not in data_row
            ):
                return False  # Hallucination: It created rows for non-existent params
    else:
        # If parameters exist, verify the LLM didn't invent NEW ones
        if len(lines) > 2:
            for row in lines[2:]:  # Skip table header and divider
                cols = [c.strip() for c in row.split("|") if c.strip()]
                if cols:
                    generated_name = cols[0].lower().replace("`", "")
                    is_valid = any(valid in generated_name for valid in valid_params)

                    # WSDL FALLBACK: Check if the parameter name was mentioned inside the text description (Zeep signature)
                    if not is_valid:
                        for p in endpoint_data.get("parameters", []):
                            desc = p.get("description", "").lower()
                            if generated_name and generated_name in desc:
                                is_valid = True
                                break

                    if not is_valid and "none" not in generated_name:
                        print(f"Hallucinated param found: {generated_name}")
                        return False  # Hallucination detected
    return True


def reflect_polish(draft_markdown: str) -> str:
    """The final QA step. The agent reviews its own completed work."""
    prompt = (
        f"Please review and polish this API documentation draft:\n\n{draft_markdown}"
    )

    try:
        response = client.models.generate_content(
            model=settings.SECONDARY_MODEL_NAME,
            contents=prompt,
            config=reviewer_config,
        )
        return response.text
    except Exception as e:
        print(f" QA Agent failed: {str(e)}. Returning the unpolished draft.")
        return draft_markdown


def run_agent(raw_content: str, progress_callback=None) -> str:
    # Add progress_callback parameter for frontend
    def log_progress(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    log_progress("Planner Agent: analyzing raw input to determine API type...")
    # use chat session to maintain conversation history
    chat = client.chats.create(
        model=settings.SECONDARY_MODEL_NAME, config=planner_config
    )

    response = chat.send_message(f"Please parse this specification:\n\n{raw_content}")

    parsed_data = None

    # check if the planner decided to use a tool
    if response.function_calls:
        function_call = response.function_calls[0]  # Get the first function call
        tool_name = function_call.name
        log_progress(f"Planner Agent: calling tool -> {tool_name}")

        # Manually pass the raw content to the tool
        # The model selected the tool, but we provide the actual content
        if tool_name == "parse_swagger":
            log_progress("System: parsing swagger...")
            parsed_data = parse_swagger(raw_content)
        elif tool_name == "parse_wsdl":
            log_progress("System: parsing wsdl...")
            parsed_data = parse_wsdl(raw_content)
    else:
        return "Error: Planner Agent failed to identify the specification format and did not call a tool."

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
            doc_chunk = generate_endpoint_doc(endpoint)
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
    final_markdown = reflect_polish(draft_markdown)

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
