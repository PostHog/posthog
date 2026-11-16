export type ContentAutopilotDiffLine = { kind: 'same' | 'added' | 'removed'; text: string }

type ContentAutopilotDiffSegment =
    | { kind: 'line'; line: ContentAutopilotDiffLine }
    | { kind: 'collapsed'; count: number }

const MAX_DIFF_CELLS = 4_000_000

function diffMiddle(beforeLines: string[], afterLines: string[]): ContentAutopilotDiffLine[] {
    if (beforeLines.length * afterLines.length > MAX_DIFF_CELLS) {
        return [
            ...beforeLines.map((text): ContentAutopilotDiffLine => ({ kind: 'removed', text })),
            ...afterLines.map((text): ContentAutopilotDiffLine => ({ kind: 'added', text })),
        ]
    }

    const width = afterLines.length + 1
    const common = new Uint32Array((beforeLines.length + 1) * width)
    for (let i = beforeLines.length - 1; i >= 0; i--) {
        for (let j = afterLines.length - 1; j >= 0; j--) {
            common[i * width + j] =
                beforeLines[i] === afterLines[j]
                    ? common[(i + 1) * width + j + 1] + 1
                    : Math.max(common[(i + 1) * width + j], common[i * width + j + 1])
        }
    }

    const lines: ContentAutopilotDiffLine[] = []
    let i = 0
    let j = 0
    while (i < beforeLines.length || j < afterLines.length) {
        if (i < beforeLines.length && j < afterLines.length && beforeLines[i] === afterLines[j]) {
            lines.push({ kind: 'same', text: afterLines[j] })
            i += 1
            j += 1
        } else if (
            j < afterLines.length &&
            (i === beforeLines.length || common[i * width + j + 1] > common[(i + 1) * width + j])
        ) {
            lines.push({ kind: 'added', text: afterLines[j] })
            j += 1
        } else {
            lines.push({ kind: 'removed', text: beforeLines[i] })
            i += 1
        }
    }
    return lines
}

export function diffLines(before: string, after: string): ContentAutopilotDiffLine[] {
    const beforeLines = before.split('\n')
    const afterLines = after.split('\n')

    let prefix = 0
    while (prefix < beforeLines.length && prefix < afterLines.length && beforeLines[prefix] === afterLines[prefix]) {
        prefix += 1
    }
    let suffix = 0
    while (
        suffix < beforeLines.length - prefix &&
        suffix < afterLines.length - prefix &&
        beforeLines[beforeLines.length - 1 - suffix] === afterLines[afterLines.length - 1 - suffix]
    ) {
        suffix += 1
    }

    const same = (text: string): ContentAutopilotDiffLine => ({ kind: 'same', text })
    return [
        ...afterLines.slice(0, prefix).map(same),
        ...diffMiddle(
            beforeLines.slice(prefix, beforeLines.length - suffix),
            afterLines.slice(prefix, afterLines.length - suffix)
        ),
        ...afterLines.slice(afterLines.length - suffix).map(same),
    ]
}

export function collapseUnchangedLines(lines: ContentAutopilotDiffLine[], context = 2): ContentAutopilotDiffSegment[] {
    const segments: ContentAutopilotDiffSegment[] = []
    const keep = (from: number, to: number): void => {
        segments.push(...lines.slice(from, to).map((line): ContentAutopilotDiffSegment => ({ kind: 'line', line })))
    }
    let start = 0
    while (start < lines.length) {
        if (lines[start].kind !== 'same') {
            keep(start, start + 1)
            start += 1
            continue
        }
        let end = start
        while (end < lines.length && lines[end].kind === 'same') {
            end += 1
        }
        const keepBefore = start === 0 ? 0 : context
        const keepAfter = end === lines.length ? 0 : context
        if (end - start > keepBefore + keepAfter + 1) {
            keep(start, start + keepBefore)
            segments.push({ kind: 'collapsed', count: end - start - keepBefore - keepAfter })
            keep(end - keepAfter, end)
        } else {
            keep(start, end)
        }
        start = end
    }
    return segments
}
