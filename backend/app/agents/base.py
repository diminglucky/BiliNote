from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    DOWNLOAD = "download"
    TRANSCRIPT = "transcript"
    NOTE_WRITER = "note_writer"
    VISUAL_INVENTORY = "visual_inventory"
    VISUAL_PLANNER = "visual_planner"
    FRAME_SELECTOR = "frame_selector"
    VISION_REVIEW = "vision_review"
    MARKDOWN_COMPOSER = "markdown_composer"
    CHAT_RAG = "chat_rag"


class StepExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    BACKGROUND = "background"


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    name: str
    description: str


@dataclass(frozen=True)
class AgentStep:
    step_id: str
    agent: AgentSpec
    mode: StepExecutionMode = StepExecutionMode.SEQUENTIAL
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    reason: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    task_id: Optional[str]
    steps: tuple[AgentStep, ...]
    diagnostics: tuple[str, ...] = ()

    def active_roles(self) -> tuple[AgentRole, ...]:
        return tuple(step.agent.role for step in self.steps)

    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)

    def has_role(self, role: AgentRole) -> bool:
        return role in self.active_roles()

    def get_step(self, step_id: str) -> Optional[AgentStep]:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def has_step(self, step_id: str) -> bool:
        return self.get_step(step_id) is not None


@dataclass(frozen=True)
class AgentExecutionContext:
    task_id: Optional[str]
    video_url: str
    platform: str
    quality: Any
    model_name: Optional[str] = None
    provider_id: Optional[str] = None
    formats: tuple[str, ...] = ()
    screenshot: bool = False
    link: bool = False
    has_prefetched_transcript: bool = False
    video_understanding: bool = False
    defer_screenshots: bool = True
    review_mode: str = "off"
    metadata: Mapping[str, Any] = field(default_factory=dict)
