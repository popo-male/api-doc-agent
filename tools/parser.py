import json
import os
import tempfile

import yaml
import zeep
from google.genai import types
from zeep.exceptions import XMLParseError


def resolve_refs(obj, full_spec, visited=None, is_openapi_3=False):
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

            if is_openapi_3:
                schemas = full_spec.get("components", {}).get("schemas", {})
            else:
                schemas = full_spec.get("definitions", {})

            resolved_schema = schemas.get(def_name, {})

            # Recursively resolve in case the definition contains more refs
            return resolve_refs(
                resolved_schema, full_spec, visited.copy(), is_openapi_3
            )

        # If it's a standard dictionary, resolve its values
        return {
            k: resolve_refs(v, full_spec, visited.copy(), is_openapi_3)
            for k, v in obj.items()
        }

    elif isinstance(obj, list):
        # If it's a list, resolve each item
        return [
            resolve_refs(item, full_spec, visited.copy(), is_openapi_3) for item in obj
        ]

    else:
        # Base case: return the value as is
        return obj


def parse_swagger(raw_string: str) -> dict:
    """
    Parses a raw Swagger 2.0 YAML string and extracts a clean list of endpoints.
    """
    try:
        # handle JSON and YAML
        spec = yaml.safe_load(raw_string)
    except yaml.YAMLError:
        return {"error": "Invalid YAML or JSON format."}

    # version check
    is_openapi_3 = "openapi" in spec
    spec_version = (
        spec.get("openapi") if is_openapi_3 else spec.get("swagger", "Unknown")
    )

    if is_openapi_3:
        servers = spec.get("servers", [{"url": "/"}])
        base_url = servers[0].get("url", "/")
    else:
        url_schema = spec.get("schemes", ["https"])[0]
        host = spec.get("host", "api.example.com")
        base_path = spec.get("basePath", "")
        base_url = f"{url_schema}://{host}{base_path}"

    # extract high-level API info
    api_info = spec.get("info", {})
    metadata = {
        "title": api_info.get("title", "Unknown API"),
        "version": api_info.get("version", "1.0"),
        "description": api_info.get("description", ""),
        "base_url": base_url,
        "securityDefinitions": spec.get("securityDefinitions", {})
        if not is_openapi_3
        else spec.get("components", {}).get("securitySchemes", {}),
    }

    paths = spec.get("paths", {})
    grouped_endpoints = {}
    flat_endpoints = []

    # loop through every URL path
    for path_url, path_data in paths.items():
        path_level_params = path_data.get("parameters", [])

        for method_name, details in path_data.items():
            # Skip non-HTTP methods like 'parameters' defined at the path level
            if method_name.lower() not in [
                "get",
                "post",
                "put",
                "delete",
                "patch",
                "options",
                "head",
            ]:
                continue

            raw_params = details.get("parameters", []) + path_level_params

            if is_openapi_3 and "requestBody" in details:
                req_body_desc = details["requestBody"].get(
                    "description", "Request Payload"
                )
                for content_type, content_data in (
                    details["requestBody"].get("content", {}).items()
                ):
                    body_schema = content_data.get("schema", {})
                    raw_params.append(
                        {
                            "name": "requestBody",
                            "in": f"body ({content_type})",
                            "description": req_body_desc,
                            "schema": body_schema,
                        }
                    )

            # Resolve parameters
            endpoint_data = {
                "path": path_url,
                "method": method_name.upper(),
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "operationId": details.get("operationId", ""),
                "parameters": resolve_refs(raw_params, spec, is_openapi_3=is_openapi_3),
                "responses": resolve_refs(
                    details.get("responses", {}), spec, is_openapi_3=is_openapi_3
                ),
            }

            flat_endpoints.append(endpoint_data)
            # Group by tags
            tags = details.get("tags", ["Untagged"])
            for tag in tags:
                if tag not in grouped_endpoints:
                    grouped_endpoints[tag] = []
                grouped_endpoints[tag].append(endpoint_data)

    return {
        "metadata": metadata,
        "spec_version": spec_version,
        "total_endpoints": len(flat_endpoints),
        "endpoints": flat_endpoints,
        "tags": grouped_endpoints,
    }


def parse_wsdl(raw_xml_string: str) -> dict:
    """
    Parses a raw SOAP WSDL XML string and extracts operations and schemas.
    Use this tool ONLY if the input looks like XML or a SOAP WSDL.
    """
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".wsdl", delete=False, encoding="utf-8"
        ) as tmp_file:
            tmp_file.write(raw_xml_string)
            tmp_file_path = tmp_file.name

        client = zeep.Client(wsdl=tmp_file_path)
        structured_endpoints = []
        api_names = []

        for service in client.wsdl.services.values():
            api_names.append(service.name)
            for port in service.ports.values():
                for operation_name, operation in port.binding._operations.items():
                    # EXACTLY what the LLM needs to understand the parameters.
                    try:
                        input_sig = (
                            operation.input.signature() if operation.input else "None"
                        )
                    except Exception:
                        input_sig = "Complex Input (Check WSDL)"

                    try:
                        output_sig = (
                            operation.output.signature() if operation.output else "None"
                        )
                    except Exception:
                        output_sig = "Complex Output (Check WSDL)"

                    endpoint_data = {
                        # use the port/operation as the path since SOAP typically hits one URL
                        "path": f"/{service.name}/{port.name}/{operation_name}",
                        "method": "POST",  # SOAP operations are universally POST requests
                        "summary": f"SOAP Operation: {operation_name}",
                        "description": f"Executes the {operation_name} action on the {port.name} port.",
                        "operationId": operation_name,
                        "parameters": [
                            {
                                "name": "SOAP Envelope",
                                "in": "body",
                                "description": f"Required XML Payload Structure:\n{input_sig}",
                            }
                        ],
                        "responses": [
                            {"description": "SOAP Response", "schema": output_sig}
                        ],
                        "tags": [port.name],  # Group endpoints by their Port name
                    }
                    structured_endpoints.append(endpoint_data)

        grouped_endpoints = {}
        for ep in structured_endpoints:
            for tag in ep["tags"]:
                if tag not in grouped_endpoints:
                    grouped_endpoints[tag] = []
                grouped_endpoints[tag].append(ep)

        final_api_title = " & ".join(api_names) if api_names else "SOAP Web Service"

        return {
            "metadata": {
                "title": final_api_title,
                "version": "1.0 (SOAP)",
                "description": "Auto-parsed SOAP WSDL Web Service. Operations are executed via XML envelopes over HTTP POST.",
                "base_url": "SOAP-Host",
            },
            "spec_version": "WSDL 1.1",
            "total_endpoints": len(structured_endpoints),
            "endpoints": structured_endpoints,
            "tags": grouped_endpoints,
        }
    except XMLParseError as e:
        return {
            "error": f"Invalid XML format. Make sure you provided a valid WSDL: {str(e)}"
        }
    except Exception as e:
        return {"error": f"Zeep failed to parse WSDL: {str(e)}"}
    finally:
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


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
