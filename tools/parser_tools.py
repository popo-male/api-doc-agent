import json

from google.genai import types


def resolve_refs(obj, full_spec, visited=None):
    """
    Recursively searches for '$ref' keys and replaces them with their
    actual definitions from the full Swagger spec.
    """
    if visited is None:
        visited = set()

    if isinstance(obj, dict):
        if "$ref" in obj:
            ref_path = obj["$ref"]

            # Prevent infinite loops from circular references
            if ref_path in visited:
                return {
                    "type": "object",
                    "description": f"Circular reference to {ref_path}",
                }
            visited.add(ref_path)

            # Parse the ref path (e.g., "#/definitions/Pet")
            def_name = ref_path.split("/")[-1]
            definitions = full_spec.get("definitions", {})
            resolved_schema = definitions.get(def_name, {})

            # Recursively resolve in case the definition contains more refs
            return resolve_refs(resolved_schema, full_spec, visited.copy())

        # If it's a standard dictionary, resolve its values
        return {k: resolve_refs(v, full_spec, visited.copy()) for k, v in obj.items()}

    elif isinstance(obj, list):
        # If it's a list, resolve each item
        return [resolve_refs(item, full_spec, visited.copy()) for item in obj]

    else:
        # Base case: return the value as is
        return obj


def parse_swagger(raw_json_string: str) -> dict:
    """
    Parses a raw Swagger 2.0 JSON string and extracts a clean list of endpoints.
    """
    try:
        spec = json.loads(raw_json_string)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON format."}

    # extract high-level API info
    api_title = spec.get("info", {}).get("title", "Unknown API")
    api_version = spec.get("info", {}).get("version", "1.0")

    paths = spec.get("paths", {})
    structured_endpoints = []

    # loop through every URL path
    for path_url, methods in paths.items():
        for method_name, details in methods.items():
            # Resolve parameters
            raw_params = details.get("parameters", [])
            resolved_params = resolve_refs(raw_params, spec)

            # Resolve responses (we just want the schema/description, not the whole HTTP header)
            raw_responses = details.get("responses", {})
            resolved_responses = resolve_refs(raw_responses, spec)

            endpoint_data = {
                "path": path_url,
                "method": method_name.upper(),
                "summary": details.get("summary", "No summary provided"),
                "parameters": resolved_params,
                "responses": resolved_responses,
            }
            structured_endpoints.append(endpoint_data)

    return {
        "api_name": api_title,
        "api_version": api_version,
        "total_endpoints": len(structured_endpoints),
        "endpoints": structured_endpoints,
    }


def parse_wsdl(raw_xml_string: str) -> dict:
    """
    Parses a raw SOAP WSDL XML string and extracts operations and schemas.
    Use this tool ONLY if the input looks like XML or a SOAP WSDL.
    """
    # Placeholder for future Zeep implementation
    return {
        "api_name": "SOAP API",
        "endpoints": [
            {
                "path": "SampleService",
                "method": "POST",
                "summary": "Sample SOAP Operation",
                "parameters": [],
                "responses": [],
            }
        ],
    }


# Create proper Tool definitions for the Gemini API
parse_swagger_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="parse_swagger",
            description="Parses a Swagger 2.0 JSON specification string and extracts API endpoints with their details including path, HTTP method, parameters, and response schemas.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "raw_json_string": types.Schema(
                        type=types.Type.STRING,
                        description="The complete Swagger/OpenAPI 2.0 JSON specification as a string. This must be the entire swagger.json content.",
                    )
                },
                required=["raw_json_string"],
            ),
        )
    ]
)

parse_wsdl_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="parse_wsdl",
            description="Parses a SOAP WSDL XML specification string and extracts operations and schemas. Use this ONLY if the input is XML or SOAP WSDL format.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "raw_xml_string": types.Schema(
                        type=types.Type.STRING,
                        description="The complete WSDL XML specification as a string.",
                    )
                },
                required=["raw_xml_string"],
            ),
        )
    ]
)


if __name__ == "__main__":
    # Paste your sample JSON here (shortened for readability)
    # sample_json = """
    # {
    #   "swagger": "2.0",
    #   "info": {"title": "Swagger Petstore", "version": "1.0.7"},
    #   "paths": {
    #     "/pet": {
    #       "post": {
    #         "summary": "Add a new pet to the store",
    #         "parameters": [{"name": "body", "in": "body", "required": true}]
    #       }
    #     }
    #   }
    # }
    # """

    # Load JSON file as string
    with open("data/swagger.json", "r", encoding="utf-8") as f:
        sample_json = f.read()

    # Run the tool and print the output
    result = parse_swagger(sample_json)
    print(json.dumps(result, indent=2))
