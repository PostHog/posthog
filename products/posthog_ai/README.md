# PostHog AI

## Skills

Agent skills live in `products/*/skills/` as Markdown or Jinja2 templates. The build system renders them into `dist/skills/` (human-readable) and packages them into `dist/skills.zip`. Both are gitignored — CI builds the ZIP from source and publishes it as a GitHub release.

### Commands

```bash
hogli build:skills          # Build skills to dist/skills/ and dist/skills.zip
hogli build:skills --list   # List discovered skills
hogli lint:skills           # Validate skill sources without rendering
```

### Workflow

1. Edit skill sources in `products/*/skills/`
2. Push to master — CI builds the ZIP and creates a GitHub release (`agent-skills-latest` + versioned)
