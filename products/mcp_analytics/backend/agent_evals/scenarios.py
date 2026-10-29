from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Scenario(BaseModel):
    """A request an agent should be able to complete against an MCP server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    intent: str = Field(min_length=10)
    success_criteria: str = Field(min_length=10)
    expected_tools: tuple[str, ...] = ()


class ScenarioFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    scenarios: tuple[Scenario, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "ScenarioFile":
        ids = [scenario.id for scenario in self.scenarios]
        duplicates = sorted({scenario_id for scenario_id in ids if ids.count(scenario_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate scenario ids: {', '.join(duplicates)}")
        return self


def load_scenarios(path: Path) -> ScenarioFile:
    return ScenarioFile.model_validate(yaml.safe_load(path.read_text()))
