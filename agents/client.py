from google import genai
from google.genai import types

from core.config import config
from core.settings import settings
from tools.parser import parse_swagger_tool, parse_wsdl_tool


class Agent:
    def __init__(self, api_key: str = None):
        self.client = genai.Client(api_key=api_key or settings.GEMINI_API_KEY)
        self.mode = None
        self.model_name = None
        self.config = None

        self._configs = {
            "planner": types.GenerateContentConfig(
                tools=[parse_swagger_tool, parse_wsdl_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode=types.FunctionCallingConfigMode.ANY,
                        allowed_function_names=["parse_swagger", "parse_wsdl"],
                    )
                ),
                system_instruction=config.model.instruction.planner,
                temperature=0.0,
            ),
            "worker": types.GenerateContentConfig(
                system_instruction=config.model.instruction.worker, temperature=0.1
            ),
            "reviewer": types.GenerateContentConfig(
                system_instruction=config.model.instruction.reviewer,
                temperature=0.1,
            ),
        }

    def set_mode(self, mode: str):
        if mode not in self._configs:
            raise ValueError(
                f"Invalid mode: {mode}. Must be one of {list(self._configs.keys())}"
            )
        self.mode = mode
        self.config = self._configs[mode]

        if mode in ["planner", "reviewer"]:
            self.model_name = settings.SECONDARY_MODEL_NAME
        else:
            self.model_name = settings.PRIMARY_MODEL_NAME

        return self

    def generate_content(self, prompt: str):
        if not self.mode:
            raise ValueError("Mode not set.")

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=self.config,
        )

        return response
