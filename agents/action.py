import json

from google.genai import errors as genai_errors
from agents.client import Agent
from core.settings import settings
from tools.parser import parse_swagger, parse_wsdl


def parse_specification(agent: Agent, raw_content: str, log_progress=None) -> dict:
    """The Planner step: Analyzes the raw string and routes it to the correct parser tool."""

    def log(msg):
        if log_progress:
            log_progress(msg)

    log("Planner Agent: analyzing raw input to determine API type...")

    agent.set_mode("planner")
    response = agent.generate_content(
        f"Please parse this specification:\n\n{raw_content}"
    )

    # Check if the planner decided to use a tool
    if response.function_calls:
        function_call = response.function_calls[0]  # Get the first function call
        tool_name = function_call.name
        log(f"Planner Agent: calling tool -> {tool_name}")

        # Manually pass the raw content to the tool
        if tool_name == "parse_swagger":
            log("System: parsing swagger...")
            return parse_swagger(raw_content)
        elif tool_name == "parse_wsdl":
            log("System: parsing wsdl...")
            return parse_wsdl(raw_content)
        else:
            return {"error": f"Unknown tool requested by Planner: {tool_name}"}
    else:
        return {
            "error": "Planner Agent failed to identify the specification format and did not call a tool."
        }


def validate_doc(doc_text: str, endpoint_data: dict) -> bool:
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


def generate_doc(agent: Agent, endpoint_data: dict, attempt=1) -> str:
    prompt = f"Please document this specific endpoint:\n{json.dumps(endpoint_data, indent=2)}"

    try:
        agent.set_mode("worker")
        response = agent.generate_content(prompt)
        doc = response.text

        if not validate_doc(doc, endpoint_data):
            print("Hallucination detected! Parameters don't match spec.")
            if attempt <= settings.MAX_RETRIES:
                print(f"Retrying... Attempt {attempt}/{settings.MAX_RETRIES}")
                return generate_doc(agent, endpoint_data, attempt + 1)
            else:
                print("Max retries reached.")
                return f"### {endpoint_data['method']} {endpoint_data['path']}\n*Error: Failed to generate accurate documentation after {settings.MAX_RETRIES} attempts.*"
        return doc
    except genai_errors.ServerError as exc:
        return f"## {endpoint_data['method']} {endpoint_data['path']}\n\nError generating documentation: {exc}"
    except Exception as exc:
        return f"### {endpoint_data['method']} {endpoint_data['path']}\n*Error: Documentation generation failed due to API connection issues.*"


def review_doc(agent: Agent, draft_markdown: str) -> str:
    """The final QA step. The agent reviews its own completed work."""
    prompt = (
        f"Please review and polish this API documentation draft:\n\n{draft_markdown}"
    )

    try:
        agent.set_mode("reviewer")
        response = agent.generate_content(prompt)
        final_text = response.text.strip()

        if final_text.startswith("```markdown"):
            final_text = final_text[11:].strip()
        if final_text.startswith("```"):
            final_text = final_text[3:].strip()
        if final_text.endswith("```"):
            final_text = final_text[:-3].strip()

        return final_text
    except Exception as e:
        print(f" QA Agent failed: {str(e)}. Returning the unpolished draft.")
        return draft_markdown
