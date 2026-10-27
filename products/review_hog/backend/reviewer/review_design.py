# `models.py` reaches these through `artefact_content.py`, so anything imported here lands on the
# `django.setup()` path. The facade contracts import nothing from Django.
from products.review_hog.backend.facade.contracts import (
    REVIEW_DESIGN_PIPELINE as REVIEW_DESIGN_PIPELINE,
    REVIEW_DESIGN_SINGLE_AGENT as REVIEW_DESIGN_SINGLE_AGENT,
)

# Why a turn runs on its design. The review-started event reports it next to the design.
REVIEW_DESIGN_REASON_FULL_MODE = "full_mode"
REVIEW_DESIGN_REASON_DEFAULT = "default"
REVIEW_DESIGN_REASON_KILL_SWITCH = "kill_switch"
