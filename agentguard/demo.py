from .models import AgentConfig, Dataset, Document, GoldCase


def seed_demo(guard):
    """Explicit, idempotent demo setup; every displayed metric comes from an actual run."""
    documents = [
        Document(id="returns", text="You can return an unused item within 30 days of delivery."),
        Document(id="shipping", text="Standard shipping takes 3 to 5 business days."),
        Document(id="support", text="Contact support at help@example.com."),
    ]
    for version in ("v1", "v2"):
        prompt_id = f"support:{version}"
        try:
            guard.store.get("prompts", prompt_id)
        except KeyError:
            guard.prompt_version(
                "support", version, "Answer using supplied evidence. If it is missing, say you do not know."
            )
        try:
            guard.store.get("agents", f"customer-support:{version}")
        except KeyError:
            guard.register_agent(
                AgentConfig(
                    name="customer-support",
                    version=version,
                    documents=documents,
                    prompt_id=prompt_id,
                    tools=["lookup_order"],
                    memory=True,
                )
            )
    try:
        guard.store.get("datasets", "support-gold:v1")
    except KeyError:
        guard.create_dataset(
            Dataset(
                name="support-gold",
                version="v1",
                cases=[
                    GoldCase(
                        id="returns",
                        input="Can I return an unused item?",
                        expected_output=documents[0].text,
                        expected_docs=["returns"],
                    ),
                    GoldCase(
                        id="shipping",
                        input="How long does standard shipping take?",
                        expected_output=documents[1].text,
                        expected_docs=["shipping"],
                    ),
                    GoldCase(
                        id="contact",
                        input="How do I contact support?",
                        expected_output=documents[2].text,
                        expected_docs=["support"],
                    ),
                    GoldCase(
                        id="unknown",
                        input="xyzzy",
                        expected_output="I do not know based on the supplied evidence.",
                    ),
                    GoldCase(
                        id="order",
                        input="Look up order 123",
                        output_schema={
                            "type": "object",
                            "properties": {
                                "order_id": {"const": "123"},
                                "status": {"const": "shipped"},
                                "source": {"const": "demo_fixture"},
                            },
                            "required": ["order_id", "status", "source"],
                        },
                        expected_tools=["lookup_order"],
                    ),
                ],
            )
        )
    return {
        "agent_id": "customer-support:v1",
        "candidate_id": "customer-support:v2",
        "dataset_id": "support-gold:v1",
    }
