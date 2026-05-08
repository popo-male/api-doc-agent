from pathlib import Path
from textwrap import dedent

import yaml
from pydantic import BaseModel, field_validator


class InstructionConfig(BaseModel):
    planner: str
    worker: str
    reviewer: str

    @field_validator("planner", "worker", "reviewer")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return dedent(value).strip()


class ModelConfig(BaseModel):
    instruction: InstructionConfig


class AppConfig(BaseModel):
    model: ModelConfig


def load_config(config_path: Path | None = None) -> AppConfig:
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"

    with config_path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file) or {}

    return AppConfig.model_validate(raw_config)


config = load_config()
