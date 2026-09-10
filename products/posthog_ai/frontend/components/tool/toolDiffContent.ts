import { Language } from 'lib/components/CodeSnippet/CodeSnippet'

/**
 * A normalized `type: "diff"` tool-call content block, as emitted by the sandbox agent's Claude
 * adapter for Edit/Write/MultiEdit/NotebookEdit calls. `oldText` is `null` for a brand-new file.
 */
export interface ToolCallDiffContent {
    type: 'diff'
    path?: string
    oldText?: string | null
    newText?: string
}

/**
 * Unwraps the ACP `{ type: 'content', content: {...} }` envelope — diff blocks may arrive flat or
 * nested under that wrapper.
 */
function unwrapBlock(block: unknown): unknown {
    if (!block || typeof block !== 'object') {
        return block
    }
    if ((block as { type?: unknown }).type === 'content' && 'content' in block) {
        return (block as { content: unknown }).content
    }
    return block
}

function asDiffContent(block: unknown): ToolCallDiffContent | null {
    const inner = unwrapBlock(block)
    if (!inner || typeof inner !== 'object' || (inner as { type?: unknown }).type !== 'diff') {
        return null
    }
    const { path, oldText, newText } = inner as { path?: unknown; oldText?: unknown; newText?: unknown }
    return {
        type: 'diff',
        path: typeof path === 'string' ? path : undefined,
        oldText: oldText === null ? null : typeof oldText === 'string' ? oldText : undefined,
        newText: typeof newText === 'string' ? newText : undefined,
    }
}

/** Every `type: "diff"` block — MultiEdit emits one per edit; the single-edit case is `[0]`. */
export function findAllDiffContent(content: unknown[]): ToolCallDiffContent[] {
    const diffs: ToolCallDiffContent[] = []
    for (const block of content) {
        const diff = asDiffContent(block)
        if (diff) {
            diffs.push(diff)
        }
    }
    return diffs
}

/**
 * Line-level +added/-removed counts via a line-frequency diff. Ported from the ../code EditToolView:
 * a missing/empty `oldText` means a new file, so every line is an addition.
 */
export function getDiffStats(
    oldText: string | null | undefined,
    newText: string | null | undefined
): { added: number; removed: number } {
    const oldLines = oldText ? oldText.split('\n') : []
    const newLines = newText ? newText.split('\n') : []

    if (!oldText) {
        return { added: newLines.length, removed: 0 }
    }

    const oldCounts = new Map<string, number>()
    for (const line of oldLines) {
        oldCounts.set(line, (oldCounts.get(line) ?? 0) + 1)
    }

    const newCounts = new Map<string, number>()
    for (const line of newLines) {
        newCounts.set(line, (newCounts.get(line) ?? 0) + 1)
    }

    let added = 0
    let removed = 0

    for (const [line, count] of newCounts) {
        const oldCount = oldCounts.get(line) ?? 0
        if (count > oldCount) {
            added += count - oldCount
        }
    }

    for (const [line, count] of oldCounts) {
        const newCount = newCounts.get(line) ?? 0
        if (count > newCount) {
            removed += count - newCount
        }
    }

    return { added, removed }
}

// The Language enum string values double as valid Monaco language ids, which is what
// MonacoDiffEditor.language wants.
const EXTENSION_LANGUAGE_MAP: Record<string, Language> = {
    ts: Language.TypeScript,
    tsx: Language.TypeScript,
    mts: Language.TypeScript,
    cts: Language.TypeScript,
    js: Language.JavaScript,
    jsx: Language.JavaScript,
    mjs: Language.JavaScript,
    cjs: Language.JavaScript,
    py: Language.Python,
    json: Language.JSON,
    sql: Language.SQL,
    go: Language.Go,
    yaml: Language.YAML,
    yml: Language.YAML,
    sh: Language.Bash,
    bash: Language.Bash,
    rb: Language.Ruby,
    java: Language.Java,
    kt: Language.Kotlin,
    php: Language.PHP,
    cs: Language.CSharp,
    swift: Language.Swift,
    html: Language.HTML,
    xml: Language.XML,
}

/** Maps a file path's extension to a Monaco language id, defaulting to plain text. */
export function languageFromPath(path?: string): Language {
    const ext = path?.split('.').pop()?.toLowerCase()
    if (!ext) {
        return Language.Text
    }
    return EXTENSION_LANGUAGE_MAP[ext] ?? Language.Text
}
