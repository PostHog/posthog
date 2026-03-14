"""
Contract types for metrics.

Stable, framework-free frozen dataclasses that define what this
product exposes to the rest of the codebase.

Characteristics:
- No Django imports
- Immutable (frozen=True)
- Used by facade as inputs/outputs

Do NOT depend on Django models, DRF serializers, or request objects.
"""
