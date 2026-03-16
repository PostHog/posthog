#!/usr/bin/env bash
# Installs PostHog agent skills and context-mill skills into the sandbox container.
# Expects the path to a directory of built skills as the first argument.
#
# PostHog skills are copied from the provided directory (built by CI).
# Context-mill skills are downloaded from GitHub releases (zip-of-zips format).
#
# Skills are copied to two locations:
#   /scripts/plugins/posthog/skills/  — Claude Code (@posthog/agent plugin discovery)
#   ~/.agents/skills/                 — Codex agent discovery

set -euo pipefail

SKILLS_SRC="${1:?Usage: install-skills.sh <skills-dir>}"
CONTEXT_MILL_ZIP_URL="https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip"
PLUGIN_SKILLS_DIR="/scripts/plugins/posthog/skills"
CODEX_SKILLS_DIR="$HOME/.agents/skills"

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

# --- Phase 1: Install PostHog skills from CI-provided directory ---

if [ -d "$SKILLS_SRC" ] && [ -n "$(ls -A "$SKILLS_SRC" 2>/dev/null)" ]; then
    cp -r "$SKILLS_SRC"/* "$PLUGIN_SKILLS_DIR/"
    cp -r "$SKILLS_SRC"/* "$CODEX_SKILLS_DIR/"
    echo "Installed PostHog skills from ${SKILLS_SRC}"
else
    echo "Warning: No PostHog skills found in ${SKILLS_SRC}." >&2
fi

# --- Phase 2: Download and install context-mill skills ---
# Context-mill publishes a zip-of-zips: the outer zip contains omnibus-*.zip files,
# each of which is a complete skill directory. We strip the "omnibus-" prefix from
# both the directory name and the SKILL.md name: field.
# This is non-fatal — if it fails, we continue with only PostHog skills.

install_context_mill_skills() {
    local tmp_dir
    tmp_dir=$(mktemp -d)
    trap 'rm -rf "$tmp_dir"' RETURN

    local outer_zip="$tmp_dir/skills-mcp-resources.zip"
    local outer_extract_dir="$tmp_dir/outer"
    local skill_extract_dir="$tmp_dir/skills"

    # Download the outer zip
    echo "Downloading context-mill skills from ${CONTEXT_MILL_ZIP_URL}..."
    curl -fsSL --retry 2 --retry-delay 3 -o "$outer_zip" "$CONTEXT_MILL_ZIP_URL"

    # Extract the outer zip
    mkdir -p "$outer_extract_dir"
    unzip -q -o "$outer_zip" -d "$outer_extract_dir"

    # Find and extract inner omnibus-*.zip files
    mkdir -p "$skill_extract_dir"

    while read -r inner_zip; do
        local base_name
        base_name=$(basename "$inner_zip" .zip)

        # Strip "omnibus-" prefix to get the skill name
        local skill_name="${base_name#omnibus-}"
        local skill_dir="$skill_extract_dir/$skill_name"

        mkdir -p "$skill_dir"
        unzip -q -o "$inner_zip" -d "$skill_dir"

        # Patch SKILL.md: remove "omnibus-" prefix from the name: field
        while read -r skill_md; do
            sed -i 's/^\(name:\s*\)omnibus-/\1/' "$skill_md"
        done < <(find "$skill_dir" -name 'SKILL.md' -type f)
    done < <(find "$outer_extract_dir" -name 'omnibus-*.zip' -type f)

    # Copy extracted skills to both target directories (overrides same-named PostHog skills)
    if [ -d "$skill_extract_dir" ] && [ -n "$(ls -A "$skill_extract_dir" 2>/dev/null)" ]; then
        cp -r "$skill_extract_dir"/* "$PLUGIN_SKILLS_DIR/"
        cp -r "$skill_extract_dir"/* "$CODEX_SKILLS_DIR/"
        echo "Installed context-mill skills"
    else
        echo "Warning: No omnibus-*.zip skills found in context-mill archive." >&2
    fi
}

if ! install_context_mill_skills; then
    echo "Warning: Failed to download/install context-mill skills. Continuing without them." >&2
fi

# --- Summary ---

skill_count=$(find "$PLUGIN_SKILLS_DIR" -name "SKILL.md" | wc -l)
echo "Installed ${skill_count} total skills to ${PLUGIN_SKILLS_DIR} and ${CODEX_SKILLS_DIR}"
