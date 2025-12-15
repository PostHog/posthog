"""
DRF views for visual_review.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to DTOs
- Call facade methods (api/api.py)
- Convert DTOs to JSON responses

No business logic here - that belongs in logic.py via the facade.
"""


# from ..api import api
