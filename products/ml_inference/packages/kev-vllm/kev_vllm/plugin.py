"""Entry points vLLM discovers: `vllm.general_plugins` registers the model classes, `vllm.io_processor_plugins` names
the IO processors. A checkpoint's config picks one of each (`architectures`, `io_processor_plugin`). Both stay lazy so
that importing this module never initializes CUDA."""


def register() -> None:
    from vllm import ModelRegistry

    ModelRegistry.register_model("KevForDecision", "kev_vllm.model:KevForDecision")
    ModelRegistry.register_model("JevK5ForDecision", "kev_vllm.jevk5_model:JevK5ForDecision")


# Dotted, not `module:attr`: vLLM resolves IO-processor plugins with importlib on the last dot.
def io_processor() -> str:
    return "kev_vllm.io_processor.KevIOProcessor"


def jevk5_io_processor() -> str:
    return "kev_vllm.jevk5_io_processor.JevK5IOProcessor"
