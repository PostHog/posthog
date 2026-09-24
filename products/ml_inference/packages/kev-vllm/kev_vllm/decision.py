"""The pointer readout: Kev's head applied to one causal row's hidden states.

A row is `state + question branch`; the branch ends with the decide token and holds one `</opt>` (box_end) token per
option. The head scores each option's `</opt>` hidden state against the decide token's hidden state, then takes a
softmax. This module is torch-only so it can be tested without vLLM and reused by the export and parity tools.
"""

import math
from collections.abc import Sequence

import torch
from torch import nn


def readout_positions(token_ids: Sequence[int], box_end_id: int, decide_id: int) -> tuple[int, list[int]]:
    """Index of the decide token and of every option-end token in one row.

    Caller-supplied text can never contain the delimiter tokens (kev_compat.user_tokens escapes them), so every
    box_end in the row belongs to an option span of this row's single question.
    """
    if not token_ids or token_ids[-1] != decide_id:
        raise ValueError("a Kev row must end with the decide token")
    opts = [i for i, t in enumerate(token_ids) if t == box_end_id]
    if not opts:
        raise ValueError("a Kev row needs at least one option")
    return len(token_ids) - 1, opts


class PointerReadout(nn.Module):
    """Kev's PointerHead with the same parameter names (`q`, `k`) so `head.pt` weights load unchanged."""

    def __init__(self, hidden_size: int, pointer_dim: int = 256, temperature: float = 1.0) -> None:
        super().__init__()
        self.q = nn.Linear(hidden_size, pointer_dim, dtype=torch.float32)
        self.k = nn.Linear(hidden_size, pointer_dim, dtype=torch.float32)
        self.scale = 1 / math.sqrt(pointer_dim)
        self.temperature = temperature

    def logits(self, h_decide: torch.Tensor, h_opts: torch.Tensor) -> torch.Tensor:
        z = (self.k(h_opts) @ self.q(h_decide)) * self.scale
        return z if self.temperature == 1.0 else z / self.temperature

    def probabilities(self, hidden_states: torch.Tensor, decide: int, opts: Sequence[int]) -> torch.Tensor:
        """Softmax over the options of one row. `hidden_states` is [L, d] in any dtype; the head runs in fp32."""
        h = hidden_states.float()
        idx = torch.as_tensor(list(opts), device=h.device)
        return torch.softmax(self.logits(h[decide], h[idx]), dim=-1)
