from litellm.integrations.custom_logger import CustomLogger

from llm_gateway.request_context import bind_private_logging_context


class PrivateScoutLoggingCallback(CustomLogger):
    async def async_pre_request_hook(self, model: str, messages: list[object], kwargs: dict[str, object]) -> None:
        # Anthropic adapters hide their provider stream inside an async generator.
        if kwargs.get("stream"):
            bind_private_logging_context(kwargs.get("litellm_logging_obj"))
