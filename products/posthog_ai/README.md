# PostHog AI

## Skills

Agent skills live in `products/*/skills/` as Markdown or Jinja2 templates. The build system renders them into `dist/skills/` (human-readable, gitignored) and packages them into `dist/skills.zip` (checked into git) for consumption by other repos.

### Commands

```bash
hogli build:skills          # Render skills to dist/skills/ for local inspection
hogli pack:skills           # Build + package into dist/skills.zip
hogli build:skills --check  # Verify dist/skills.zip matches sources (CI)
hogli build:skills --list   # List discovered skills
hogli lint:skills           # Validate skill sources without rendering
```

### Workflow

1. Edit skill sources in `products/*/skills/`
2. Run `hogli pack:skills` to regenerate the ZIP
3. Commit both source changes and `dist/skills.zip`

CI will fail if the ZIP is out of date.
