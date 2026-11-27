import { Language, getLanguage } from 'lib/components/CodeSnippet'

import type { FeatureFlagCodeBranchApi } from './generated/api.schemas'

// File extensions whose language name differs from the extension. Anything else goes through getLanguage.
const EXTENSION_LANGUAGES: Record<string, Language> = {
    mjs: Language.JavaScript,
    cjs: Language.JavaScript,
    mts: Language.TypeScript,
    cts: Language.TypeScript,
    pyi: Language.Python,
    kt: Language.Kotlin,
    kts: Language.Kotlin,
    cs: Language.CSharp,
    rs: Language.Rust,
    ex: Language.Elixir,
    exs: Language.Elixir,
    m: Language.ObjectiveC,
    mm: Language.ObjectiveC,
    h: Language.C,
    cc: Language.CPlusPlus,
    cxx: Language.CPlusPlus,
    hpp: Language.CPlusPlus,
    hh: Language.CPlusPlus,
    gradle: Language.Groovy,
    vue: Language.HTML,
    svelte: Language.HTML,
    erb: Language.Ruby,
}

export function languageForFile(path: string): Language {
    const fileName = path.split('/').pop() ?? ''
    const extension = fileName.includes('.') ? (fileName.split('.').pop()?.toLowerCase() ?? '') : ''
    return EXTENSION_LANGUAGES[extension] ?? getLanguage(extension)
}

function indentWidth(line: string): number {
    return line.length - line.trimStart().length
}

/**
 * Remove the indentation every line of a branch body shares, so a body nested deep in the file reads
 * from the left edge while keeping its own structure.
 *
 * Agents often copy the first line without its leading whitespace. When the first line starts at
 * column 0 but every other line is indented, the other lines are dedented on their own.
 */
export function dedentSnippet(snippet: string): string {
    const lines = snippet.replace(/\s+$/, '').split('\n')
    const [first, ...rest] = lines
    const isCode = (line: string): boolean => line.trim().length > 0
    const restWidths = rest.filter(isCode).map(indentWidth)
    if (restWidths.length === 0) {
        return first.trimStart()
    }
    const restIndent = Math.min(...restWidths)
    const firstIndent = indentWidth(first)
    const strip = (line: string, width: number): string => (isCode(line) ? line.slice(width) : '')

    if (firstIndent === 0 && restIndent > 0) {
        return [first, ...rest.map((line) => strip(line, restIndent))].join('\n')
    }
    const indent = Math.min(firstIndent, restIndent)
    return lines.map((line) => strip(line, indent)).join('\n')
}

export type OutcomeTone = 'off' | 'on' | 'neutral'

export interface OutcomePresentation {
    label: string
    caption: string
    tone: OutcomeTone
    /** Shows the variant key in a monospace font. */
    isVariantKey: boolean
}

export function describeOutcome(variant: string): OutcomePresentation {
    switch (variant) {
        case 'disabled':
            return { label: 'Flag off', caption: 'Before', tone: 'off', isVariantKey: false }
        case 'enabled':
            return { label: 'Flag on', caption: 'After', tone: 'on', isVariantKey: false }
        case 'all':
            return {
                label: 'Every outcome',
                caption: 'Same code, only the flag value passed to it changes',
                tone: 'neutral',
                isVariantKey: false,
            }
        case 'control':
            return { label: variant, caption: 'Control', tone: 'neutral', isVariantKey: true }
        default:
            return { label: variant, caption: 'Variant', tone: 'on', isVariantKey: true }
    }
}

// Before on the left, after on the right: off first, then on, then control ahead of the other variants.
function outcomeRank(variant: string): number {
    switch (variant) {
        case 'all':
            return 0
        case 'disabled':
            return 1
        case 'enabled':
            return 2
        case 'control':
            return 3
        default:
            return 4
    }
}

export function sortBranches(branches: FeatureFlagCodeBranchApi[]): FeatureFlagCodeBranchApi[] {
    // Array.prototype.sort is stable, so variants keep the order the analysis reported them in.
    return [...branches].sort((a, b) => outcomeRank(a.variant) - outcomeRank(b.variant))
}
