import json
import os

from fastapi import HTTPException

from .providers import ProviderClient, ProviderError
from .service import AgentGuard


class BudgetedProvider:
    def __init__(self, accounts, workspace_id, provider=None):
        self.accounts = accounts
        self.workspace_id = workspace_id
        self.provider = provider or ProviderClient()

    def complete(self, spec, messages, tools, max_tokens=1024):
        live = spec.provider != "demo"
        cost = 0.0
        if live:
            catalog = json.loads(os.getenv("AGENTGUARD_MODEL_PRICES", "{}"))
            approved = catalog.get(f"{spec.provider}/{spec.model}")
            if not approved or any(
                approved.get(k) != getattr(spec, k) for k in ("input_per_million", "output_per_million")
            ):
                raise ProviderError(
                    "Live model and rates must match the operator's AGENTGUARD_MODEL_PRICES catalog"
                )
            if (
                spec.input_per_million is None
                or spec.output_per_million is None
                or spec.input_per_million <= 0
                or spec.output_per_million <= 0
            ):
                raise ProviderError("Approved live model prices must be positive")
            # Conservative reservation, not invoice accounting. Keep it charged even on errors.
            input_bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 1024 * (
                len(messages) + len(tools) + 1
            )
            cost = (input_bound * spec.input_per_million + max_tokens * spec.output_per_million) / 1_000_000
        try:
            self.accounts.reserve(self.workspace_id, calls=1, cost=cost, live=live)
        except HTTPException as exc:
            raise ProviderError(exc.detail) from exc
        return self.provider.complete(spec, messages, tools, max_tokens)


class WorkspaceGuard(AgentGuard):
    def __init__(self, accounts, workspace_id, provider=None):
        self.accounts = accounts
        self.workspace_id = workspace_id
        super().__init__(accounts.path_for(workspace_id), BudgetedProvider(accounts, workspace_id, provider))

    def execute_agent(self, *args, **kwargs):
        self.accounts.reserve(self.workspace_id, runs=1)
        return super().execute_agent(*args, **kwargs)
