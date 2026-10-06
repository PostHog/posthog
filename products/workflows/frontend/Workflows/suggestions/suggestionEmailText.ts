import type { SuggestedFieldChange } from './suggestionChanges'

export type EmailTextDiffPart =
    | { kind: 'same' | 'removed' | 'added'; text: string }
    // Unchanged text left out of the summary.
    | { kind: 'gap' }

const BLOCK_ELEMENTS = 'p, div, td, th, tr, li, br, h1, h2, h3, h4, h5, h6, table, section, blockquote'

// Above this many word pairs the full diff costs more than it is worth on every render.
const MAX_DIFF_CELLS = 4_000_000

export function isEmailHtmlChange(change: SuggestedFieldChange): boolean {
    return /(^|\.)email\.value\.html$/.test(change.path)
}

export function emailVisibleText(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('head, style, script, noscript, template').forEach((node) => node.remove())
    // Email markup rarely leaves whitespace between blocks, so their text would otherwise run together.
    doc.body?.querySelectorAll(BLOCK_ELEMENTS).forEach((node) => node.after(' '))
    return (doc.body?.textContent ?? '').replace(/\s+/g, ' ').trim()
}

function words(text: string): string[] {
    return text ? text.split(' ') : []
}

function pushPart(parts: EmailTextDiffPart[], kind: 'same' | 'removed' | 'added', word: string): void {
    const last = parts[parts.length - 1]
    if (last && last.kind === kind) {
        last.text = `${last.text} ${word}`
    } else {
        parts.push({ kind, text: word })
    }
}

export function diffEmailText(before: string, after: string): EmailTextDiffPart[] {
    const a = words(before)
    const b = words(after)
    let start = 0
    while (start < a.length && start < b.length && a[start] === b[start]) {
        start++
    }
    let endA = a.length
    let endB = b.length
    while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
        endA--
        endB--
    }

    const parts: EmailTextDiffPart[] = []
    a.slice(0, start).forEach((word) => pushPart(parts, 'same', word))

    const midA = a.slice(start, endA)
    const midB = b.slice(start, endB)
    if (midA.length * midB.length > MAX_DIFF_CELLS) {
        midA.forEach((word) => pushPart(parts, 'removed', word))
        midB.forEach((word) => pushPart(parts, 'added', word))
    } else {
        // Longest common subsequence over the words that differ, walked from the front.
        const rows = midA.length + 1
        const cols = midB.length + 1
        const lengths = new Uint32Array(rows * cols)
        for (let i = midA.length - 1; i >= 0; i--) {
            for (let j = midB.length - 1; j >= 0; j--) {
                lengths[i * cols + j] =
                    midA[i] === midB[j]
                        ? lengths[(i + 1) * cols + j + 1] + 1
                        : Math.max(lengths[(i + 1) * cols + j], lengths[i * cols + j + 1])
            }
        }
        let i = 0
        let j = 0
        while (i < midA.length && j < midB.length) {
            if (midA[i] === midB[j]) {
                pushPart(parts, 'same', midA[i++])
                j++
            } else if (lengths[(i + 1) * cols + j] >= lengths[i * cols + j + 1]) {
                pushPart(parts, 'removed', midA[i++])
            } else {
                pushPart(parts, 'added', midB[j++])
            }
        }
        midA.slice(i).forEach((word) => pushPart(parts, 'removed', word))
        midB.slice(j).forEach((word) => pushPart(parts, 'added', word))
    }

    a.slice(endA).forEach((word) => pushPart(parts, 'same', word))
    return groupChanges(parts)
}

// A rewrite shares stray words like "the" with the original, and showing those as unchanged
// interleaves both versions into text nobody wrote. Fold short unchanged runs between changes
// into the change, so it reads as one removed passage and one added passage.
const MIN_KEPT_WORDS = 3

function groupChanges(parts: EmailTextDiffPart[]): EmailTextDiffPart[] {
    const grouped: EmailTextDiffPart[] = []
    let removed: string[] = []
    let added: string[] = []
    const flush = (): void => {
        if (removed.length) {
            grouped.push({ kind: 'removed', text: removed.join(' ') })
        }
        if (added.length) {
            grouped.push({ kind: 'added', text: added.join(' ') })
        }
        removed = []
        added = []
    }
    parts.forEach((part, index) => {
        if (part.kind === 'removed') {
            removed.push(part.text)
        } else if (part.kind === 'added') {
            added.push(part.text)
        } else if (part.kind === 'same') {
            const between = index > 0 && index < parts.length - 1
            if (between && part.text.split(' ').length < MIN_KEPT_WORDS) {
                removed.push(part.text)
                added.push(part.text)
            } else {
                flush()
                grouped.push(part)
            }
        }
    })
    flush()
    return grouped
}

/** Keeps every change with a few words either side, so a reader sees what moved without the whole email. */
export function condenseEmailTextDiff(parts: EmailTextDiffPart[], context = 5): EmailTextDiffPart[] {
    const condensed: EmailTextDiffPart[] = []
    parts.forEach((part, index) => {
        if (part.kind !== 'same') {
            condensed.push(part)
            return
        }
        const partWords = part.text.split(' ')
        const isFirst = index === 0
        const isLast = index === parts.length - 1
        const keepFront = isFirst ? 0 : context
        const keepBack = isLast ? 0 : context
        if (partWords.length <= keepFront + keepBack) {
            condensed.push(part)
            return
        }
        if (keepFront) {
            condensed.push({ kind: 'same', text: partWords.slice(0, keepFront).join(' ') })
        }
        condensed.push({ kind: 'gap' })
        if (keepBack) {
            condensed.push({ kind: 'same', text: partWords.slice(-keepBack).join(' ') })
        }
    })
    return condensed
}
