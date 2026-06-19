/**
 * Detection of stale tool/skill references in help texts — phrases like "use the X tool"
 * or "load the X skill" that resemble a real tool/skill name but don't resolve. Name-level
 * only: this cannot validate documented schemas or tool behavior.
 *
 * The check is heuristic and advisory (callers surface findings, they never block): a candidate
 * is only flagged when it *resembles* a real name — within NEAR_MISS_MAX_EDITS of one, or an exact
 * casing miss. Backticks are not treated as intent (prose uses them for emphasis and field names
 * too), so anything that doesn't resemble a real name is ignored and no name-level allowlist is
 * needed.
 *
 * Used by scripts/lint-tool-names.ts. The skills lint (products/posthog_ai/scripts/
 * build_skills.py) implements the same rules for skill markdown, plus one deliberately
 * skills-only rule: call-syntax references like `read_data("experiments", id)` occur
 * only in skill prose, and detecting them here would false-positive on SDK/HogQL code
 * examples in tool descriptions.
 */

// Tool-name validation (length/pattern) findings — kept blocking by the caller.
export type Violation = { source: string; tool: string; reason: string }

// A heuristic, advisory reference finding, located on the offending line so the caller can render
// it as an inline annotation.
export type ReferenceFinding = { source: string; line: number; col: number; name: string; message: string }

// The kinds produced by the phrase regex alternation `(tools?|skills?)`.
type ReferenceKind = 'tool' | 'tools' | 'skill' | 'skills'

// A candidate is only treated as a (stale) reference when it is within this many edits of a real
// name. Real renames/typos sit at distance 1-2 from the intended tool; ordinary hyphenated prose
// ("highest-error", "per-file") is far from every name and so is ignored.
const NEAR_MISS_MAX_EDITS = 2

// "use the X tool", "load the `X` skill" — kebab or snake candidate followed by tool/skill.
const PHRASE_REFERENCE = /(?<![A-Za-z0-9_`-])`?([a-z0-9]+(?:[_-][a-z0-9]+)+)`?\s+(tools?|skills?)\b/g
// "via `X`", "use `X`" — kebab-only (snake here is usually a field/SDK name, not a tool).
const INVOCATION_REFERENCE =
    /\b(?:via|use|using|call|calling)\s+(?:the\s+)?`([a-z0-9]+(?:-[a-z0-9]+)+)`(?!\s*(?:tools?|skills?)\b)/g
// A noun right after the backticked name means it's not a tool reference ("via the `x` feature flag").
const ENTITY_NOUN_AFTER = /^\s+(?:feature|flag|event|property|properties|column|field|table|key|filter)s?\b/
// Backticked snake_case whose kebab form is a real tool — wrong casing.
const SNAKE_CASE_REFERENCE = /`([a-z0-9]+(?:_[a-z0-9]+)+)`/g

function lineCol(text: string, offset: number): { line: number; col: number } {
    const before = text.slice(0, offset)
    const lastNewline = before.lastIndexOf('\n')
    return { line: (before.match(/\n/g)?.length ?? 0) + 1, col: offset - lastNewline }
}

function isValidReference(name: string, kind: ReferenceKind, toolNames: Set<string>, skillNames: Set<string>): boolean {
    const registry = kind === 'skill' || kind === 'skills' ? skillNames : toolNames
    if (registry.has(name)) {
        return true
    }
    // Shorthand suffix, e.g. "the partial-update tool" for external-data-schemas-partial-update.
    for (const known of registry) {
        if (known.endsWith(`-${name}`)) {
            return true
        }
    }
    // Plural family reference, e.g. "the feature-flag tools".
    if (kind === 'tools' || kind === 'skills') {
        for (const known of registry) {
            if (known.startsWith(`${name}-`)) {
                return true
            }
        }
    }
    return false
}

function editDistance(a: string, b: string): number {
    let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
    for (let i = 1; i <= a.length; i++) {
        const cur = [i]
        for (let j = 1; j <= b.length; j++) {
            cur.push(Math.min(prev[j]! + 1, cur[j - 1]! + 1, prev[j - 1]! + (a[i - 1] === b[j - 1] ? 0 : 1)))
        }
        prev = cur
    }
    return prev[b.length]!
}

// Real names this candidate plausibly meant: exact/suffix matches, else near-misses by edit distance.
function referenceSuggestions(name: string, registry: Set<string>): string[] {
    const kebab = name.replace(/_/g, '-')
    const suffix = [...registry].filter((t) => t === kebab || t.endsWith(`-${kebab}`)).sort()
    if (suffix.length > 0) {
        return suffix
    }
    return [...registry]
        .map((known) => ({ known, distance: editDistance(kebab, known) }))
        .filter(({ distance }) => distance <= NEAR_MISS_MAX_EDITS)
        .sort((a, b) => a.distance - b.distance || a.known.localeCompare(b.known))
        .map(({ known }) => known)
}

function didYouMean(suggestions: string[]): string {
    return suggestions.length > 0 ? ` — did you mean ${suggestions.join(' or ')}?` : ''
}

export function checkReferencesInText(
    text: string,
    source: string,
    toolNames: Set<string>,
    skillNames: Set<string>,
    seen: Set<string>,
    findings: ReferenceFinding[]
): void {
    // Dedupe by name across all scanned texts: the generated JSONs and snapshots repeat the YAML
    // and serializer texts, and one name tripping two rules (e.g. wrong casing inside a phrase)
    // is one finding. First report wins, so callers scan hand-editable sources first.
    const report = (offset: number, name: string, message: string): void => {
        if (seen.has(name)) {
            return
        }
        seen.add(name)
        const { line, col } = lineCol(text, offset)
        findings.push({ source, line, col, name, message })
    }

    // "X tool/skill". Resemblance to a real name is the only signal we trust — backticks in prose
    // mean emphasis or a field name as often as a reference, so they are not treated as intent.
    for (const match of text.matchAll(PHRASE_REFERENCE)) {
        const name = match[1]!
        const kind = match[2] as ReferenceKind
        if (isValidReference(name, kind, toolNames, skillNames)) {
            continue
        }
        const registry = kind === 'skill' || kind === 'skills' ? skillNames : toolNames
        const suggestions = referenceSuggestions(name, registry)
        if (suggestions.length > 0) {
            // The match begins at the optional leading backtick, then the name.
            const offset = match.index + (match[0].startsWith('`') ? 1 : 0)
            report(
                offset,
                name,
                `'${name}' looks like a ${kind.replace(/s$/, '')} but none exists${didYouMean(suggestions)}`
            )
        }
    }
    // "via `X`": one concrete thing, but not whether tool or skill — check tools (a family prefix
    // like `feature-flag` is not invocable) plus exact skill names.
    for (const match of text.matchAll(INVOCATION_REFERENCE)) {
        if (ENTITY_NOUN_AFTER.test(text.slice(match.index + match[0].length))) {
            continue
        }
        const name = match[1]!
        if (isValidReference(name, 'tool', toolNames, skillNames) || skillNames.has(name)) {
            continue
        }
        const suggestions = referenceSuggestions(name, toolNames)
        if (suggestions.length > 0) {
            // The name sits just after the first backtick in the match.
            const offset = match.index + match[0].indexOf('`') + 1
            report(offset, name, `'${name}' looks like a tool but none exists${didYouMean(suggestions)}`)
        }
    }
    for (const match of text.matchAll(SNAKE_CASE_REFERENCE)) {
        const name = match[1]!
        if (!toolNames.has(name) && toolNames.has(name.replace(/_/g, '-'))) {
            const offset = match.index + 1 // skip the opening backtick
            report(offset, name, `'${name}' has wrong casing — the tool is named ${name.replace(/_/g, '-')}`)
        }
    }
}
