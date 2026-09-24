"""vLLM model class for JevK5: the Qwen3.5 causal LM, pooled to the answer letters' next-token logits.

Registered under the architecture name `JevK5ForDecision` by `kev_vllm.plugin.register`. The exported checkpoint
(`kev_vllm.jevk5_export`) is JevK5's own weights with `jevk5_letter_token_ids` and `jevk5_temperature` added to its
config. The pooler returns raw logits; the IO processor applies the temperature and the softmax over the question's
options, because only it knows how many options each row has.
"""

from collections.abc import Set as AbstractSet

import torch
from vllm.config import VllmConfig
from vllm.model_executor.layers.pooler import Pooler, PoolingParamsUpdate
from vllm.model_executor.layers.pooler.tokwise import AllPool
from vllm.model_executor.models.interfaces_base import default_pooling_type
from vllm.model_executor.models.qwen3_5 import Qwen3_5ForCausalLM
from vllm.tasks import PoolingTask
from vllm.v1.outputs import PoolerOutput
from vllm.v1.pool.metadata import PoolingMetadata


class JevK5Pooler(Pooler):
    def __init__(self, lm_head: torch.nn.Module, letter_token_ids: list[int]) -> None:
        super().__init__()
        self.lm_head = lm_head
        self.letter_token_ids = letter_token_ids
        self.all_pool = AllPool()

    def get_supported_tasks(self) -> AbstractSet[PoolingTask]:
        return {"plugin"}

    def get_pooling_updates(self, task: PoolingTask) -> PoolingParamsUpdate:
        return PoolingParamsUpdate()

    def forward(self, hidden_states: torch.Tensor, pooling_metadata: PoolingMetadata) -> PoolerOutput:
        rows = self.all_pool(hidden_states, pooling_metadata)
        # Read per call: the weights load after construction, and the tied lm_head shares the embedding tensor.
        letter_weights = self.lm_head.weight[self.letter_token_ids].float()
        return [None if row is None else letter_weights @ row[-1].float() for row in rows]


@default_pooling_type(seq_pooling_type="LAST", tok_pooling_type="ALL")
class JevK5ForDecision(Qwen3_5ForCausalLM):
    is_pooling_model = True

    def __init__(self, *, vllm_config: VllmConfig, prefix: str = "") -> None:
        super().__init__(vllm_config=vllm_config, prefix=prefix)
        config = vllm_config.model_config.hf_text_config
        self.pooler = JevK5Pooler(self.lm_head, letter_token_ids=list(config.jevk5_letter_token_ids))
