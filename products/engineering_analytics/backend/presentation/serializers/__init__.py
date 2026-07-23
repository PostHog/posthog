"""DRF serializers for engineering_analytics.

Output-only serializers that turn the facade's frozen dataclasses into JSON via
``DataclassSerializer``, one module per surface area mirroring ``views/``. Field
types are auto-derived from the contract types; ``help_text`` is added through
``Meta.extra_kwargs`` so it flows downstream into the OpenAPI spec, generated
TypeScript types, and the ``pr_lifecycle`` MCP tool schema. Leaf serializers
nested by more than one domain module live in ``_shared``.
"""
