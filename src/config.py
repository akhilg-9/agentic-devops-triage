"""Project-wide configuration: env + YAML prompt config.

Two layers:
- `settings`        — env-loaded runtime settings (API keys, default paths).
- `load_prompt_config(version)` — returns the active YAML prompt config
                                  validated through pydantic.

Code that previously hard-coded prompt strings now reads them from a
PromptConfig object built once per process. Bumping prompts/v*.yaml is the
unit of change that the eval suite gates on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


# ----------------------------------------------------------------------------
# Env-driven settings
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    router_model: str = os.environ.get("ROUTER_MODEL", "")    # overrides YAML
    planner_model: str = os.environ.get("PLANNER_MODEL", "")  # overrides YAML
    agent_model: str = os.environ.get("AGENT_MODEL", "")      # overrides YAML
    judge_model: str = os.environ.get("JUDGE_MODEL", "")      # overrides YAML
    prompts_dir: str = os.environ.get("TRIAGE_PROMPTS_DIR", "prompts")
    runbook_dir: str = os.environ.get("TRIAGE_RUNBOOK_DIR", "data/runbooks")


settings = Settings()


# ----------------------------------------------------------------------------
# YAML prompt config schema
# ----------------------------------------------------------------------------


class ModelConfig(BaseModel):
    provider: Literal["openai"] = "openai"
    router_model: str
    planner_model: str
    agent_model: str
    judge_model: str
    temperature: float = 0.0


class RetrievalConfig(BaseModel):
    top_k: int = 3
    bm25_k_constant: float = 1.5
    bm25_b: float = 0.75


class RouterPromptConfig(BaseModel):
    prompt_version: Literal["baseline", "improved"] = "improved"
    system_baseline: str
    system_improved: str

    @property
    def system(self) -> str:
        return self.system_improved if self.prompt_version == "improved" else self.system_baseline


class PlannerPromptConfig(BaseModel):
    prompt_version: Literal["baseline", "improved"] = "improved"
    system_baseline: str
    system_improved: str

    @property
    def system(self) -> str:
        return self.system_improved if self.prompt_version == "improved" else self.system_baseline


class AgentPromptConfig(BaseModel):
    max_iterations: int = Field(default=6, ge=1, le=30)
    system: str


class JudgePromptConfig(BaseModel):
    system: str


class PromptConfig(BaseModel):
    version: str
    description: str = ""
    model: ModelConfig
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    router: RouterPromptConfig
    planner: PlannerPromptConfig
    agent: AgentPromptConfig
    judge: JudgePromptConfig

    # --- Env overrides for model ids: env wins so users can A/B without YAML edits ---

    def router_model(self) -> str:
        return settings.router_model or self.model.router_model

    def planner_model(self) -> str:
        return settings.planner_model or self.model.planner_model

    def agent_model(self) -> str:
        return settings.agent_model or self.model.agent_model

    def judge_model(self) -> str:
        return settings.judge_model or self.model.judge_model


def load_prompt_config(version: Optional[str] = None, prompts_dir: Optional[str] = None) -> PromptConfig:
    """Load prompts/<version>.yaml. If `version` is None, picks the highest v*.yaml on disk."""
    prompts_dir = Path(prompts_dir or settings.prompts_dir)
    if version is None:
        candidates = sorted(prompts_dir.glob("v*.yaml"))
        if not candidates:
            raise FileNotFoundError(f"no prompt configs in {prompts_dir}")
        path = candidates[-1]
    else:
        path = prompts_dir / f"{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"prompt config not found: {path}")
    raw = yaml.safe_load(path.read_text())
    return PromptConfig.model_validate(raw)
