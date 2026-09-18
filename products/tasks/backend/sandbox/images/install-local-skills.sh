#!/usr/bin/env bash
set -euo pipefail

source_dir="${1:?Expected a local skill directory or --restore}"
plugin_dir="${2:-/scripts/plugins/posthog}"

if [[ "$source_dir" != "--restore" ]] && ! compgen -G "$source_dir/*/SKILL.md" > /dev/null; then
    echo "Local skill snapshot contains no rendered skills." >&2
    exit 1
fi

for target in "$plugin_dir/skills" "$HOME/.agents/skills" "$HOME/.claude/skills"; do
    backup="$target.posthog-base"
    manifest="$target.posthog-local"
    if [[ -f "$manifest" ]]; then
        while IFS= read -r name; do
            case "$name" in ''|.*|*/*) echo "Invalid local skill name" >&2; exit 1 ;; esac
            rm -rf -- "$target/$name"
            if [[ -e "$backup/$name" ]]; then
                cp -a "$backup/$name" "$target/$name"
            fi
        done < "$manifest"
        rm -rf -- "$backup" "$manifest"
    fi
    if [[ "$source_dir" == "--restore" ]]; then
        continue
    fi
    mkdir -p "$target" "$backup"
    for skill in "$source_dir"/*; do
        [[ -d "$skill" && -f "$skill/SKILL.md" ]] || continue
        name="$(basename "$skill")"
        if [[ -e "$target/$name" ]]; then
            cp -a "$target/$name" "$backup/$name"
        fi
        printf '%s\n' "$name" >> "$manifest"
        rm -rf -- "$target/$name"
        cp -a "$skill" "$target/$name"
    done
done
