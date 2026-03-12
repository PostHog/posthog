#!/usr/bin/env bash
# Downloads and installs PostHog agent skills from GitHub releases.
# Used inside sandbox containers to dynamically inject skills before the agent starts.
#
# Skills are extracted to /scripts/plugins/posthog/skills/ which the @posthog/agent
# package discovers via its plugin directory convention.

set -euo pipefail

SKILLS_DIR="/scripts/plugins/posthog/skills"
RELEASE_URL="https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills.zip"
TMP_DIR=$(mktemp -d)

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "Downloading skills from ${RELEASE_URL}..."
if ! curl -fsSL --connect-timeout 10 --max-time 30 -o "$TMP_DIR/skills.zip" "$RELEASE_URL"; then
    echo "Warning: Failed to download skills. Continuing without skills." >&2
    exit 0
fi

echo "Extracting skills..."
unzip -q -o "$TMP_DIR/skills.zip" -d "$TMP_DIR/extracted"

# Find the skills directory within the extracted content.
# The zip may contain a top-level directory or skills directly.
EXTRACTED_SKILLS=""
if [ -d "$TMP_DIR/extracted/skills" ]; then
    EXTRACTED_SKILLS="$TMP_DIR/extracted/skills"
else
    # Look one level deep for a skills directory
    for dir in "$TMP_DIR/extracted"/*/; do
        if [ -d "${dir}skills" ]; then
            EXTRACTED_SKILLS="${dir}skills"
            break
        fi
    done
fi

# Fall back to looking for SKILL.md files at the top level
if [ -z "$EXTRACTED_SKILLS" ]; then
    # Check if extracted content itself contains skill directories (dirs with SKILL.md)
    has_skills=false
    for dir in "$TMP_DIR/extracted"/*/; do
        if [ -f "${dir}SKILL.md" ]; then
            has_skills=true
            break
        fi
    done
    if [ "$has_skills" = true ]; then
        EXTRACTED_SKILLS="$TMP_DIR/extracted"
    fi
fi

if [ -z "$EXTRACTED_SKILLS" ]; then
    echo "Warning: No skills found in downloaded archive." >&2
    exit 0
fi

# Set up the plugin directory structure
mkdir -p "$SKILLS_DIR"

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

# Copy skills, replacing any existing ones
rm -rf "$SKILLS_DIR"/*
cp -r "$EXTRACTED_SKILLS"/* "$SKILLS_DIR/"

skill_count=$(find "$SKILLS_DIR" -name "SKILL.md" | wc -l)
echo "Installed ${skill_count} skills to ${SKILLS_DIR}"
