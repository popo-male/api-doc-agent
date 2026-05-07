import json
import sys
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


def generate_endpoint_doc(endpoint_data: dict, attempt=1) -> str:
    print(f"Documenting: {endpoint_data['method']} {endpoint_data['path']})")
    prompt = f"Please document this specific endpoint:\n{json.dumps(endpoint_data, indent=2)}"

    try:
        response = client.models.generate_content(
            model=settings.MODEL_NAME, contents=prompt, config=worker_config
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

    # if the spec has no parameters, but llm outputed a table with rows, flag it as false
    if (
        not valid_params
        and "|"
        in doc_text.split("### Request Parameters")[-1].split("#### Request Payload")[0]
    ):
        if "None" not in doc_text.split("#### Request Parameters")[-1]:
            return False
    return True


def run_agent(raw_content: str) -> str:
    print("Planner: analyzing raw input to determine API type...")
    # use chat session to maintain conversation history
    chat = client.chats.create(model=settings.MODEL_NAME, config=planner_config)

    response = chat.send_message(f"Please parse this specification:\n\n{raw_content}")

    parsed_data = None

    # check if the planner decided to use a tool
    if response.function_calls:
        function_call = response.function_calls[0]  # Get the first function call
        tool_name = function_call.name
        print(f"Planner: calling tool -> {tool_name}")

        # Manually pass the raw content to the tool
        # The model selected the tool, but we provide the actual content
        if tool_name == "parse_swagger":
            print("System: parsing swagger...")
            parsed_data = parse_swagger(raw_content)
        elif tool_name == "parse_wsdl":
            print("System: parsing wsdl...")
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
        print(
            f"Warning: Spec contains {total_endpoints} endpoints. Truncating to {settings.MAX_ENDPOINTS_PER_RUN} to save API limits."
        )

    print("System: successfully extracted endpoints. Beginning documentation...")

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

            doc_chunk = generate_endpoint_doc(endpoint)
            grouped_docs[tag_name].append(doc_chunk)
            processed_count += 1

    # assembly
    print("\nSystem: All endpoints documented! Passing to Jinja2 template...")
    final_markdown = render_final_markdown(metadata, grouped_docs)

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
