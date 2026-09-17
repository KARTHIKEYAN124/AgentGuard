from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSpec(Record):
    provider: Literal["demo", "openai", "anthropic", "gemini", "ollama"] = "demo"
    model: str = Field(default="demo-grounded", min_length=1, max_length=150)
    input_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class Document(Record):
    id: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=50000)


class AgentConfig(Record):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    version: str = Field(min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    model: ModelSpec = Field(default_factory=ModelSpec)
    reasoning_model: ModelSpec | None = None
    fallbacks: list[ModelSpec] = Field(default_factory=list, max_length=5)
    prompt_id: str | None = None
    system_prompt: str = Field(
        default="Answer using supplied evidence. If it is missing, say you do not know.", max_length=30000
    )
    tools: list[Literal["knowledge_search", "lookup_order"]] = Field(default_factory=list)
    retrieval: bool = True
    documents: list[Document] = Field(default_factory=list, max_length=1000)
    memory: bool = False
    max_steps: int = Field(default=5, ge=1, le=10)
    max_output_tokens: int = Field(default=1024, ge=32, le=8192)
    output_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def unique_docs(self):
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("Document IDs must be unique")
        return self


class ExecuteRequest(Record):
    agent_id: str
    input: str = Field(min_length=1, max_length=30000)
    task: Literal["auto", "extraction", "reasoning"] = "auto"
    session_id: str | None = Field(default=None, max_length=150)
    experiment_id: str | None = None
    subject_id: str | None = Field(default=None, max_length=150)


class GoldCase(Record):
    id: str = Field(min_length=1, max_length=100)
    input: str = Field(min_length=1, max_length=30000)
    expected_output: str | None = None
    expected_docs: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    expected_tools: list[str] = Field(default_factory=list)


class Dataset(Record):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    cases: list[GoldCase] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique")
        if any(c.expected_output is None and c.output_schema is None for c in self.cases):
            raise ValueError(
                "Every case needs expected_output or output_schema for a reproducible accuracy score"
            )
        return self


class SuiteRequest(Record):
    agent_id: str
    dataset_id: str
    baseline_id: str | None = None
    judge_model: ModelSpec | None = None


class PromptRequest(Record):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    template: str = Field(min_length=1, max_length=30000)


class ExperimentRequest(Record):
    name: str = Field(min_length=1, max_length=100)
    agent_a: str
    agent_b: str
    allocation_a: float = Field(default=0.5, gt=0, lt=1, allow_inf_nan=False)


class Metrics(Record):
    accuracy: float = Field(ge=0, le=1, allow_inf_nan=False)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)


class JudgeRequest(Record):
    input: str = Field(min_length=1, max_length=30000)
    response: str = Field(max_length=50000)
    rubric: str = Field(default="Assess correctness, relevance, safety, and completeness.", max_length=10000)
    sources: list[str] = Field(default_factory=list, max_length=100)
    model: ModelSpec


class JudgeScores(Record):
    correctness: float = Field(ge=0, le=1, allow_inf_nan=False)
    relevance: float = Field(ge=0, le=1, allow_inf_nan=False)
    safety: float = Field(ge=0, le=1, allow_inf_nan=False)
    completeness: float = Field(ge=0, le=1, allow_inf_nan=False)
    faithfulness: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    rationale: str
