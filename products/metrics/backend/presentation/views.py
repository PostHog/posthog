"""
DRF views for metrics.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to frozen dataclasses
- Call facade methods (facade/api.py)
- Convert frozen dataclasses to JSON responses

No business logic here - that belongs in logic.py via the facade.
"""


# from ..facade import api
