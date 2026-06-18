"""Agent Skills spec packaging and Claude Code plugin-marketplace serving for skills.

- ``packaging`` — Django-free SKILL.md serialization + zip / marketplace file-tree assembly
- ``git_smart_http`` — Django-free read-only Git Smart HTTP synthesis of the marketplace repo
- ``adapters`` — the only ORM-aware layer: turns ``LLMSkill`` rows into the plain export dataclasses
- ``auth`` — Basic-auth -> Project Secret API Key bridge so ``git clone`` can authenticate
"""
