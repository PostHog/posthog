/**
 * Detection of stale tool/skill references in help texts — phrases like "use the X tool"
 * or "load the X skill" must point at an existing tool/skill. Name-level only: this cannot
 * validate documented schemas or tool behavior.
 *
 * Used by scripts/lint-tool-names.ts. The skills lint (products/posthog_ai/scripts/
 * build_skills.py) implements the same rules for skill markdown, plus one deliberately
 * skills-only rule: call-syntax references like `read_data("experiments", id)` occur
 * only in skill prose, and detecting them here would false-positive on SDK/HogQL code
 * examples in tool descriptions.
 */

export type Violation = { source: string; tool: string; reason: string }

// The kinds produced by the phrase regex alternation `(tools?|skills?)`.
type ReferenceKind = 'tool' | 'tools' | 'skill' | 'skills'

// Names that read like a tool/skill reference but aren't one. Bare prose ("a per-file tool") is
// handled structurally by the near-miss gate below — it only flags a candidate that resembles a
// real name — so the allowlist only needs names that survive that gate: those referenced inside
// backticks, which are kept strict.
const REFERENCE_ALLOWLIST = new Set([
    'skills-store', // the Skills store feature, referenced as `skills-store`
    'llma-alerts', // skills-store skill, referenced in backticks; not in this repo
    'text-embedding-3-small-1536', // embedding model name
])

// A bare prose candidate is only treated as a (stale) reference when it is within this many edits
// of a real name. Real renames/typos sit at distance 1-2 from the intended tool; ordinary
// hyphenated adjectives ("highest-error", "per-file") are far from every name and so are ignored.
const NEAR_MISS_MAX_EDITS = 2

// "use the X tool", "load the `X` skill" — kebab or snake candidate followed by tool/skill.
// Group 1 captures a leading backtick: a backticked name is a literal identifier (kept strict),
// a bare name is prose (gated by near-miss resemblance to a real name).
const PHRASE_REFERENCE = /(?<![A-Za-z0-9_`-])(`?)([a-z0-9]+(?:[_-][a-z0-9]+)+)`?\s+(tools?|skills?)\b/g
// "via `X`", "use `X`" — kebab-only (snake here is usually a field/SDK name, not a tool).
const INVOCATION_REFERENCE =
    /\b(?:via|use|using|call|calling)\s+(?:the\s+)?`([a-z0-9]+(?:-[a-z0-9]+)+)`(?!\s*(?:tools?|skills?)\b)/g
// A noun right after the backticked name means it's not a tool reference ("via the `x` feature flag").
const ENTITY_NOUN_AFTER = /^\s+(?:feature|flag|event|property|properties|column|field|table|key|filter)s?\b/
// Backticked snake_case whose kebab form is a real tool — wrong casing.
const SNAKE_CASE_REFERENCE = /`([a-z0-9]+(?:_[a-z0-9]+)+)`/g

type PhraseReference = { backticked: boolean; name: string; kind: ReferenceKind }

function findPhraseReferences(text: string): PhraseReference[] {
    return [...text.matchAll(PHRASE_REFERENCE)].map((match) => ({
        backticked: match[1] === '`', // group 1 is the optional leading backtick
        name: match[2]!, // the name always captures on a match
        kind: match[3] as ReferenceKind, // guaranteed by the `(tools?|skills?)` alternation
    }))
}

function findInvocationReferences(text: string): string[] {
    const names: string[] = []
    for (const match of text.matchAll(INVOCATION_REFERENCE)) {
        if (!ENTITY_NOUN_AFTER.test(text.slice(match.index + match[0].length))) {
            names.push(match[1]!)
        }
    }
    return names
}

function findBacktickedSnakeCase(text: string): string[] {
    return [...text.matchAll(SNAKE_CASE_REFERENCE)].map((match) => match[1]!)
}

function isValidReference(name: string, kind: ReferenceKind, toolNames: Set<string>, skillNames: Set<string>): boolean {
    if (REFERENCE_ALLOWLIST.has(name)) {
        return true
    }
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
    violations: Violation[]
): void {
    // Dedupe by name across all scanned texts: the generated JSONs and snapshots repeat the YAML
    // and serializer texts, and one name tripping two rules (e.g. wrong casing inside a phrase)
    // is one mistake. First report wins, so callers scan hand-editable sources first.
    const report = (name: string, reason: string): void => {
        if (seen.has(name)) {
            return
        }
        seen.add(name)
        violations.push({ source, tool: name, reason })
    }

    for (const { backticked, name, kind } of findPhraseReferences(text)) {
        if (isValidReference(name, kind, toolNames, skillNames)) {
            continue
        }
        const registry = kind === 'skill' || kind === 'skills' ? skillNames : toolNames
        const suggestions = referenceSuggestions(name, registry)
        // A backticked name is a literal identifier, so an unknown one is always a mistake; a bare
        // prose name is only a reference when it resembles a real one (a near-miss), not when it is
        // an ordinary hyphenated adjective like "highest-error".
        if (backticked || suggestions.length > 0) {
            report(name, `references nonexistent ${kind.replace(/s$/, '')}${didYouMean(suggestions)}`)
        }
    }
    // "via `X`" names one concrete thing but not whether it's a tool or skill: check tools with
    // singular kind (a family prefix like `feature-flag` is not invocable), plus exact skill names.
    for (const name of findInvocationReferences(text)) {
        if (!isValidReference(name, 'tool', toolNames, skillNames) && !skillNames.has(name)) {
            report(name, `references nonexistent tool${didYouMean(referenceSuggestions(name, toolNames))}`)
        }
    }
    for (const name of findBacktickedSnakeCase(text)) {
        if (!toolNames.has(name) && toolNames.has(name.replace(/_/g, '-'))) {
            report(name, `wrong casing — the tool is named ${name.replace(/_/g, '-')}`)
        }
    }
}
