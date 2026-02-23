from fwma.core.config import FWMAConfig, ModelsConfig


def test_validate_model_credentials_all_present():
    config = FWMAConfig(
        gemini_api_key="g",
        anthropic_api_key="a",
        openai_api_key="o",
        models=ModelsConfig(
            screener="gemini/gemini-2.5-flash",
            chair="anthropic/claude-sonnet-4",
            member1="openai/gpt-4o",
            member2="gemini/gemini-2.5-pro",
        ),
    )
    config.validate_model_credentials()


def test_validate_model_credentials_missing_required_key():
    config = FWMAConfig(
        gemini_api_key="",
        anthropic_api_key="",
        openai_api_key="o",
        models=ModelsConfig(
            screener="gemini/gemini-2.5-flash",
            chair="anthropic/claude-sonnet-4",
            member1="openai/gpt-4o",
            member2="openai/gpt-4o",
        ),
    )

    try:
        config.validate_model_credentials()
        assert False, "Expected ValueError"
    except ValueError as exc:
        message = str(exc)
        assert "GEMINI_API_KEY" in message
        assert "ANTHROPIC_API_KEY" in message


def test_validate_model_credentials_ignores_unknown_provider():
    config = FWMAConfig(
        gemini_api_key="",
        anthropic_api_key="",
        openai_api_key="",
        models=ModelsConfig(
            screener="custom/my-model",
            chair="custom/my-model",
            member1="custom/my-model",
            member2="custom/my-model",
        ),
    )
    config.validate_model_credentials()
