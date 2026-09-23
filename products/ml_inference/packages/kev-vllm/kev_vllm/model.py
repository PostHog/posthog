"""vLLM model class for Kev: Qwen3.5 backbone plus the pointer readout as a pooler.

Registered under the architecture name `KevForDecision` by `kev_vllm.plugin.register`. The exported checkpoint
(`kev_vllm.export`) is a text-only Qwen3.5 config with the fields below, the merged bf16 backbone under `model.*`,
and the fp32 head under `head.*`.
"""

from collections.abc import Iterable
from collections.abc import Set as AbstractSet

import torch
from vllm.config import VllmConfig
from vllm.model_executor.layers.pooler import Pooler, PoolingParamsUpdate
from vllm.model_executor.layers.pooler.tokwise import AllPool
from vllm.model_executor.model_loader.weight_utils import default_weight_loader
from vllm.model_executor.models.interfaces_base import default_pooling_type
from vllm.model_executor.models.qwen3_5 import Qwen3_5ForCausalLM
from vllm.tasks import PoolingTask
from vllm.v1.outputs import PoolerOutput
from vllm.v1.pool.metadata import PoolingMetadata

from kev_vllm.decision import PointerReadout, readout_positions

HEAD_PREFIX = "head."


class KevPooler(Pooler):
    """Turns each finished row's hidden states into that question's probability vector."""

    def __init__(self, readout: PointerReadout, box_end_id: int, decide_id: int) -> None:
        super().__init__()
        self.readout = readout
        self.box_end_id = box_end_id
        self.decide_id = decide_id
        self.all_pool = AllPool()

    def get_supported_tasks(self) -> AbstractSet[PoolingTask]:
        return {"plugin"}

    def get_pooling_updates(self, task: PoolingTask) -> PoolingParamsUpdate:
        return PoolingParamsUpdate(requires_token_ids=True)

    def forward(self, hidden_states: torch.Tensor, pooling_metadata: PoolingMetadata) -> PoolerOutput:
        rows = self.all_pool(hidden_states, pooling_metadata)
        token_ids = pooling_metadata.get_prompt_token_ids_cpu()
        outputs: list[torch.Tensor | None] = []
        for row_hidden, row_ids in zip(rows, token_ids, strict=True):
            if row_hidden is None:
                outputs.append(None)
                continue
            ids = row_ids.tolist()
            if not ids or ids[-1] != self.decide_id:
                # vLLM's start-up warm-up pools rows of zero token ids; they carry no question, so they get no answer.
                outputs.append(row_hidden.new_zeros(1, dtype=torch.float32))
                continue
            decide, opts = readout_positions(ids, self.box_end_id, self.decide_id)
            outputs.append(self.readout.probabilities(row_hidden, decide, opts))
        return outputs


@default_pooling_type(seq_pooling_type="LAST", tok_pooling_type="ALL")
class KevForDecision(Qwen3_5ForCausalLM):
    is_pooling_model = True

    def __init__(self, *, vllm_config: VllmConfig, prefix: str = "") -> None:
        super().__init__(vllm_config=vllm_config, prefix=prefix)
        config = vllm_config.model_config.hf_text_config
        self.head = PointerReadout(config.hidden_size, config.kev_head_dim, temperature=config.kev_temperature)
        self.pooler = KevPooler(self.head, box_end_id=config.kev_box_end_token_id, decide_id=config.kev_decide_token_id)

    def load_weights(self, weights: Iterable[tuple[str, torch.Tensor]]) -> set[str]:
        head_params = dict(self.head.named_parameters())
        loaded: set[str] = set()

        def backbone_weights() -> Iterable[tuple[str, torch.Tensor]]:
            for name, weight in weights:
                if name.startswith(HEAD_PREFIX):
                    param = head_params[name[len(HEAD_PREFIX) :]]
                    default_weight_loader(param, weight.to(param.dtype))
                    loaded.add(name)
                else:
                    yield name, weight

        return super().load_weights(backbone_weights()) | loaded
