"""vLLM IO-processor plugin for JevK5: a TypeSafe `/v1/systemone` request in, answers in the same shape as Kev's out.

`pre_process` returns one prompt per question, each carrying the whole state, so vLLM batches the questions like any
other rows. `post_process` turns each row's letter logits into that question's probabilities.
"""

from collections.abc import Sequence

from transformers import AutoTokenizer
from vllm.config import VllmConfig
from vllm.inputs import TokensPrompt
from vllm.outputs import PoolingRequestOutput
from vllm.plugins.io_processors.interface import IOProcessor
from vllm.renderers import BaseRenderer

from kev_vllm import jevk5
from kev_vllm.io_processor import PendingRequests
from kev_vllm.kev_compat import Question, SystemOneRequest, output_tokens, to_answers, to_record


class JevK5IOProcessor(IOProcessor[SystemOneRequest, dict]):
    def __init__(self, vllm_config: VllmConfig, renderer: BaseRenderer) -> None:
        super().__init__(vllm_config, renderer)
        model_config = vllm_config.model_config
        self.tokenizer = AutoTokenizer.from_pretrained(model_config.tokenizer, revision=model_config.tokenizer_revision)
        self.served_model = model_config.served_model_name
        self.temperature = float(model_config.hf_text_config.jevk5_temperature)
        self._pending: PendingRequests[tuple[list[Question], list[dict], int]] = PendingRequests()

    def parse_data(self, data: object) -> SystemOneRequest:
        return SystemOneRequest.model_validate(data)

    def pre_process(self, prompt: SystemOneRequest, request_id: str | None = None, **kwargs) -> Sequence[TokensPrompt]:
        questions = list(prompt.questions.values())
        rows = [jevk5.prompt_ids(self.tokenizer, prompt.state, question) for question in questions]
        _, meta = to_record(prompt)
        self._pending.put(request_id, (questions, meta, sum(len(row) for row in rows)))
        return [TokensPrompt(prompt_token_ids=row) for row in rows]

    def post_process(self, model_output: Sequence[PoolingRequestOutput], request_id: str | None = None, **kwargs) -> dict:
        questions, meta, input_tokens = self._pending.take(request_id)
        if len(model_output) != len(questions):
            raise ValueError(f"got {len(model_output)} rows back for {len(questions)} questions")
        probs = [
            jevk5.probabilities(out.outputs.data.tolist(), question, self.temperature, question_meta["keys"])
            for out, question, question_meta in zip(model_output, questions, meta, strict=True)
        ]
        answers = to_answers(probs, meta)
        return {
            "model": self.served_model,
            "answers": answers,
            "probabilities_raw": probs,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens(self.tokenizer, answers)},
        }
