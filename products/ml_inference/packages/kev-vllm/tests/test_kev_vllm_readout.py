import math

import torch

from kev_vllm.decision import PointerReadout


def test_probabilities_match_the_pointer_formula():
    torch.manual_seed(0)
    readout = PointerReadout(hidden_size=8, pointer_dim=4, temperature=1.0)
    hidden = torch.randn(6, 8, dtype=torch.bfloat16)
    probs = readout.probabilities(hidden, decide=5, opts=[1, 3])
    h = hidden.float()
    expected = torch.softmax((readout.k(h[[1, 3]]) @ readout.q(h[5])) / math.sqrt(4), dim=-1)
    assert probs.dtype == torch.float32
    assert torch.allclose(probs, expected)
    assert math.isclose(probs.sum().item(), 1.0, abs_tol=1e-6)


def test_temperature_flattens_without_changing_the_argmax():
    torch.manual_seed(1)
    hidden = torch.randn(5, 8)
    raw = PointerReadout(8, 4, temperature=1.0)
    cooled = PointerReadout(8, 4, temperature=3.0)
    cooled.load_state_dict(raw.state_dict())
    p_raw = raw.probabilities(hidden, decide=4, opts=[0, 1, 2])
    p_cooled = cooled.probabilities(hidden, decide=4, opts=[0, 1, 2])
    assert p_raw.argmax() == p_cooled.argmax()
    assert p_cooled.max() < p_raw.max()
