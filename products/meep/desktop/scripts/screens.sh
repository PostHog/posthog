#!/bin/sh
# Render the app's key screens from fixtures and stitch one collage per theme,
# for reviewing a UI change across every page at once.
#
#   sh scripts/screens.sh [name]    writes .scratch/screens/<name>/ (default: latest)
#
# Each screen is saved as light-<screen>.png and dark-<screen>.png, beside
# collage-light.png and collage-dark.png. Needs ffmpeg for the collages.
set -eu
cd "$(dirname "$0")/.."

command -v ffmpeg >/dev/null 2>&1 || { echo 'The collages need ffmpeg: brew install ffmpeg' >&2; exit 127; }

out=".scratch/screens/${1:-latest}"
rm -rf "$out"
mkdir -p "$out"
screens="agent-chat,agent-working,agent-prompt,sidebar-card,agent-overview,agent-needs,agent-inbox,agent-report,agent-tasks,agent-task,tasks-board,agent-files,agent-routines,routines,agent-mission,agent-goals,agent-goal,agent-facts,agent-fact,agent-linked,agent-linked-item,agent-rules,new-topic,empty-chat,search,settings,settings-connections,settings-appearance"

MEEP_PREVIEW_DIR="$PWD/$out" MEEP_PREVIEW_ONLY="$screens" \
    cargo test -q -p meep --features ui-previews --test previews

python3 - "$out" "$screens" <<'PY'
import os, subprocess, sys

out, screens = sys.argv[1], sys.argv[2].split(",")
cols, w = 4, 900
h = w * 2 // 3
for theme in ("light", "dark"):
    files = [f"{out}/{theme}-{s}.png" for s in screens if os.path.exists(f"{out}/{theme}-{s}.png")]
    if not files:
        continue
    n = len(files)
    rows = (n + cols - 1) // cols
    pad = cols * rows - n
    inputs = [arg for f in files for arg in ("-i", f)]
    graph = "".join(
        f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:0:0:color=gray[s{i}];"
        for i in range(n)
    )
    graph += "".join(f"color=gray:s={w}x{h}[e{j}];" for j in range(pad))
    cells = [f"[s{i}]" for i in range(n)] + [f"[e{j}]" for j in range(pad)]
    layout = "|".join(f"{(k % cols) * w}_{(k // cols) * h}" for k in range(cols * rows))
    graph += "".join(cells) + f"xstack=inputs={cols * rows}:layout={layout}[o]"
    target = f"{out}/collage-{theme}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[o]", target],
        check=True,
    )
    print(f"{n} screens -> {target}")
PY
