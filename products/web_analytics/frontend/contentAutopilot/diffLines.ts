export type ContentAutopilotDiffLine = { kind: 'same' | 'added' | 'removed'; text: string }

export type ContentAutopilotDiffSegment =
    | { kind: 'line'; line: ContentAutopilotDiffLine }
    | { kind: 'collapsed'; count: number }

const MAX_DIFF_CELLS = 4_000_000

export function diffLines(before: string, after: string): ContentAutopilotDiffLine[] {
    const beforeLines = before.split('\n')
    const afterLines = after.split('\n')
    const beforeKeys = beforeLines.map((line) => line.trimEnd())
    const afterKeys = afterLines.map((line) => line.trimEnd())

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
                beforeKeys[i] === afterKeys[j]
                    ? common[(i + 1) * width + j + 1] + 1
                    : Math.max(common[(i + 1) * width + j], common[i * width + j + 1])
        }
    }

    const lines: ContentAutopilotDiffLine[] = []
    let i = 0
    let j = 0
    while (i < beforeLines.length || j < afterLines.length) {
        if (i < beforeLines.length && j < afterLines.length && beforeKeys[i] === afterKeys[j]) {
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

export function collapseUnchangedLines(lines: ContentAutopilotDiffLine[], context = 2): ContentAutopilotDiffSegment[] {
    const segments: ContentAutopilotDiffSegment[] = []
    let start = 0
    while (start < lines.length) {
        if (lines[start].kind !== 'same') {
            segments.push({ kind: 'line', line: lines[start] })
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
            lines.slice(start, start + keepBefore).forEach((line) => segments.push({ kind: 'line', line }))
            segments.push({ kind: 'collapsed', count: end - start - keepBefore - keepAfter })
            lines.slice(end - keepAfter, end).forEach((line) => segments.push({ kind: 'line', line }))
        } else {
            lines.slice(start, end).forEach((line) => segments.push({ kind: 'line', line }))
        }
        start = end
    }
    return segments
}
