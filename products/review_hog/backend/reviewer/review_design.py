# Kept free of imports: `models.py` reaches these through `artefact_content.py`, so anything imported
# here lands on the `django.setup()` path.

# How a turn finds its issues, decided per turn at fetch. Plain strings, like the review mode.
REVIEW_DESIGN_PIPELINE = "pipeline"
REVIEW_DESIGN_SINGLE_AGENT = "single_agent"

# Why a turn runs on its design. The review-started event reports it next to the design.
REVIEW_DESIGN_REASON_FULL_MODE = "full_mode"
REVIEW_DESIGN_REASON_DEFAULT = "default"
REVIEW_DESIGN_REASON_KILL_SWITCH = "kill_switch"
