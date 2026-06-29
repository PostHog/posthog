from parameterized import parameterized

from products.replay_vision.backend.temporal.masking import summarize_masking_config


class TestSummarizeMaskingConfig:
    @parameterized.expand(
        [
            ("none", None),
            ("empty", {}),
            ("inputs_disabled", {"maskAllInputs": False}),
        ]
    )
    def test_no_masking_returns_none(self, _name, config):
        summary, fully_masked = summarize_masking_config(config)
        assert summary is None
        assert fully_masked is False

    def test_total_privacy_is_fully_masked(self):
        summary, fully_masked = summarize_masking_config(
            {"maskTextSelector": "*", "maskAllInputs": True, "blockSelector": "img"}
        )
        assert fully_masked is True
        assert summary is not None
        assert "all on-screen text is masked" in summary

    def test_input_masking_is_annotated_not_skipped(self):
        summary, fully_masked = summarize_masking_config({"maskAllInputs": True})
        assert fully_masked is False
        assert summary == "text typed into input fields is masked"

    def test_narrow_text_selector_is_annotated_not_skipped(self):
        summary, fully_masked = summarize_masking_config({"maskTextSelector": ".pii", "maskAllInputs": False})
        assert fully_masked is False
        assert summary == "on-screen text matching the selector `.pii` is masked"

    def test_block_selector_is_described(self):
        summary, fully_masked = summarize_masking_config({"blockSelector": ".avatar", "maskAllInputs": False})
        assert fully_masked is False
        assert summary is not None
        assert "elements matching the selector `.avatar` are blocked out" in summary
