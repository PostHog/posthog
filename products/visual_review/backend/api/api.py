"""
Facade API for visual_review.

This is the ONLY module other apps are allowed to import.

Not to be confused with HTTP APIs (views/serializers).

Responsibilities:
- Accept DTOs as input parameters
- Call domain logic (logic.py)
- Convert Django models to DTOs before returning
- Enforce transactions where needed
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets
"""
