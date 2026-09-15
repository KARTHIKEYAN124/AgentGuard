"""Run `uv run python main.py` and open http://127.0.0.1:8000."""

import os

from dotenv import load_dotenv

load_dotenv(".env.local")
from agentguard.api import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("AGENTGUARD_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("AGENTGUARD_API_TOKEN"):
        raise SystemExit("AGENTGUARD_API_TOKEN is required when binding outside loopback")
    uvicorn.run(app, host=host, port=int(os.getenv("PORT", "8000")))
