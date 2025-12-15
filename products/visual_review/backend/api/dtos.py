"""
DTOs for visual_review API.

Stable, framework-free dataclasses that serve as internal contracts.

Characteristics:
- No Django imports
- Immutable (frozen=True)
- Used by facade as inputs/outputs

Do NOT depend on Django models, DRF serializers, or request objects.
"""
