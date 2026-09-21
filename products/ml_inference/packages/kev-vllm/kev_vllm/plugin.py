"""Entry points vLLM discovers: `vllm.general_plugins` registers the model class, `vllm.io_processor_plugins` names
the IO processor. Both stay lazy so that importing this module never initializes CUDA."""


def register() -> None:
    from vllm import ModelRegistry

    ModelRegistry.register_model("KevForDecision", "kev_vllm.model:KevForDecision")


def io_processor() -> str:
    return "kev_vllm.io_processor:KevIOProcessor"
