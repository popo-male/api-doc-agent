from jinja2 import Template

# This is the master layout for your API documentation
MARKDOWN_TEMPLATE = """# {{ metadata.title | default('API') }} Documentation

## Overview
- **Base URL:** `{{ base_url }}`
- **API Version:** `{{ metadata.version | default('1.0') }}`

{% if metadata.description %}
{{ metadata.description }}
{% endif %}

## Authentication
{% if not security %}
This API does not require authentication.
{% else %}
{% for sec_name, sec_details in security.items() %}
**Method:** {{ sec_name }} ({{ sec_details.type }})
- **Included in:** `{{ sec_details.in | default('header') }}` as `{{ sec_details.name | default('Authorization') }}`
{% if sec_details.type == 'apiKey' or sec_details.type == 'oauth2' %}
- **Example:** `{{ sec_details.name | default('Authorization') }}: Bearer <your_token>`
{% else %}
- **Example:** `{{ sec_details.name | default('Authorization') }}: <credentials>`
{% endif %}

{% endfor %}
{% endif %}

---

## Endpoints

{% for tag_name, endpoints in grouped_docs.items() %}
### Category: {{ tag_name | capitalize }}
---
{% for doc in endpoints %}
{{ doc }}

---
{% endfor %}
{% endfor %}
"""

def render_final_markdown(metadata: dict, grouped_docs: dict) -> str:
    """
    Takes the pure metadata and the LLM-generated endpoint chunks,
    and injects them into the Jinja2 template.
    """
    # Calculate the base URL dynamically
    scheme = metadata.get('schemes', ['https'])[0]
    host = metadata.get('host', 'api.example.com')
    base_path = metadata.get('basePath', '')
    base_url = f"{scheme}://{host}{base_path}"

    template = Template(MARKDOWN_TEMPLATE)

    return template.render(
        metadata=metadata,
        base_url=base_url,
        security=metadata.get('securityDefinitions', {}),
        grouped_docs=grouped_docs
    )