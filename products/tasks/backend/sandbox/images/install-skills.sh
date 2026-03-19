#!/usr/bin/env bash
# Installs pre-built agent skills into the sandbox container.
# Expects the path to a directory of built skills as the first argument.
# The directory should contain both PostHog skills (from CI build) and
# context-mill skills.
#
# Skills are copied to two locations:
#   /scripts/plugins/posthog/skills/  — Claude Code (@posthog/agent plugin discovery)
#   ~/.agents/skills/                 — Codex agent discovery

set -euo pipefail

SKILLS_SRC="${1:?Usage: install-skills.sh <skills-dir>}"
PLUGIN_SKILLS_DIR="/scripts/plugins/posthog/skills"
CODEX_SKILLS_DIR="$HOME/.agents/skills"

if [ ! -d "$SKILLS_SRC" ] || [ -z "$(find "$SKILLS_SRC" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)" ]; then
    echo "Warning: No skills found in ${SKILLS_SRC}. Continuing without skills." >&2
    exit 0
fi

# Set up directory structure
mkdir -p "$PLUGIN_SKILLS_DIR"
mkdir -p "$CODEX_SKILLS_DIR"

# Create plugin.json if it doesn't exist
PLUGIN_JSON="/scripts/plugins/posthog/plugin.json"
if [ ! -f "$PLUGIN_JSON" ]; then
    cat > "$PLUGIN_JSON" << 'EOF'
{
    "name": "posthog",
    "description": "PostHog skills for background agents",
    "version": "1.0.0"
}
EOF
fi

# Copy skills to both locations
cp -r "$SKILLS_SRC"/* "$PLUGIN_SKILLS_DIR/"
cp -r "$SKILLS_SRC"/* "$CODEX_SKILLS_DIR/"

skill_count=$(find "$PLUGIN_SKILLS_DIR" -name "SKILL.md" | wc -l)
echo "Installed ${skill_count} skills to ${PLUGIN_SKILLS_DIR} and ${CODEX_SKILLS_DIR}"
