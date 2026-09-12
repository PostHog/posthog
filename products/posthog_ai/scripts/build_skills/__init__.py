"""Build coding agent skills from products/*/skills/ into rendered files and a ZIP archive.

Skills can be:
- Plain markdown (SKILL.md) — copied as-is
- Jinja2 templates (SKILL.md.j2) — rendered with Python context including Pydantic schema helpers

Each skill must have YAML frontmatter with at least ``name`` and ``description`` fields.
The build renders skills to dist/skills/{skill_name}/ (gitignored, human-readable)
and optionally packages them into dist/skills.zip (published as a GitHub release by CI).

Requires the project's Python environment (managed by uv) for template rendering
that imports Pydantic models from product code.

One module per concern; import the module you need, never this package.
"""
