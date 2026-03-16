"""
Facade for tracing.

This is the ONLY module other products are allowed to import.

Responsibilities:
- Accept frozen dataclasses as input parameters
- Call business logic (logic.py)
- Convert Django models to frozen dataclasses before returning
- Enforce transactions where needed
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets
"""


# --- Converters (model -> frozen dataclass) ---
#
# These look repetitive when fields align 1:1. The value is having ONE place
# where "internal" becomes "external contract". When models and contracts drift,
# the mapper absorbs the change instead of it leaking everywhere.
