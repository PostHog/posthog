"""vLLM IO-processor plugin: a TypeSafe `/v1/systemone` request in, Kev's answers out.

`pre_process` encodes the request the way Kev does and returns one causal row per question, so vLLM batches rows
across requests. `post_process` maps each row's probability vector back onto the question it came from.
"""

import threading
import time
from collections import deque
from collections.abc import Sequence

from transformers import AutoTokenizer
from vllm.config import VllmConfig
from vllm.inputs import TokensPrompt
from vllm.outputs import PoolingRequestOutput
from vllm.plugins.io_processors.interface import IOProcessor
from vllm.renderers import BaseRenderer

from kev_vllm.kev_compat import SystemOneRequest, encode, output_tokens, rows_of, to_answers, to_record

# Serving limits, as kev.serve: the per-branch cap mirrors Jev's window and the base model bounds both.
INFER_MAX_STATE, INFER_MAX_BRANCH = 8192, 8192
# A request aborted between pre_process and post_process never collects its entry, so old ones are swept. vLLM has no
# abort hook for IO processors and bounds admission rather than request age, so the age is set far beyond any wait a
# caller survives: the gateway gives up on a request in well under a minute.
PENDING_SWEEP_SIZE, PENDING_MAX_AGE_SECONDS = 10_000, 3600


class KevIOProcessor(IOProcessor[SystemOneRequest, dict]):
    def __init__(self, vllm_config: VllmConfig, renderer: BaseRenderer) -> None:
        super().__init__(vllm_config, renderer)
        model_config = vllm_config.model_config
        self.tokenizer = AutoTokenizer.from_pretrained(model_config.tokenizer, revision=model_config.tokenizer_revision)
        self.served_model = model_config.served_model_name
        # request_id -> (question metadata, input token count, enqueued at); vLLM calls pre_process and post_process
        # with the same id
        self._pending: dict[str | None, deque[tuple[list[dict], int, float]]] = {}
        # vLLM may run pre_process and post_process on executor threads, so every access to the map is serialised.
        self._pending_lock = threading.Lock()

    def parse_data(self, data: object) -> SystemOneRequest:
        return SystemOneRequest.model_validate(data)

    def pre_process(self, prompt: SystemOneRequest, request_id: str | None = None, **kwargs) -> Sequence[TokensPrompt]:
        record, meta = to_record(prompt)
        enc = encode(self.tokenizer, record, max_state=INFER_MAX_STATE, max_branch=INFER_MAX_BRANCH)
        state_ids, _, rows = rows_of(enc)
        with self._pending_lock:
            if len(self._pending) > PENDING_SWEEP_SIZE:
                self._sweep_pending()
            self._pending.setdefault(request_id, deque()).append((meta, len(enc["ids"]), time.monotonic()))
        return [TokensPrompt(prompt_token_ids=state_ids + row["ids"]) for row in rows]

    def post_process(self, model_output: Sequence[PoolingRequestOutput], request_id: str | None = None, **kwargs) -> dict:
        with self._pending_lock:
            entries = self._pending.get(request_id)
            if not entries:
                raise ValueError(f"request {request_id} waited longer than {PENDING_MAX_AGE_SECONDS}s and was swept")
            meta, input_tokens, _ = entries.popleft()
            if not entries:
                del self._pending[request_id]
        probs = [out.outputs.data.tolist() for out in model_output]
        if len(probs) != len(meta):
            raise ValueError(f"got {len(probs)} rows back for {len(meta)} questions")
        answers = to_answers(probs, meta)
        return {
            "model": self.served_model,
            "answers": answers,
            "probabilities_raw": probs,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens(self.tokenizer, answers)},
        }

    def _sweep_pending(self) -> None:
        """Caller holds the lock."""
        cutoff = time.monotonic() - PENDING_MAX_AGE_SECONDS
        for request_id in [rid for rid, entries in self._pending.items() if entries[0][2] < cutoff]:
            del self._pending[request_id]
