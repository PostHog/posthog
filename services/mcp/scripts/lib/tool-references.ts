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

// Hyphenated/underscored prose that reads like a tool/skill reference but isn't one.
const REFERENCE_ALLOWLIST = new Set([
    'per-file', // "a per-file tool"
    'follow-up', // "a follow-up tool"
    'pre-approved', // "list of pre-approved tools"
    'built-in', // "a built-in tool"
    'heavily-used', // "a heavily-used tool"
    'harness-level', // "a harness-level tool"
    'product-specific', // "a product-specific tool"
    'time-to-merge', // "there is no aggregate time-to-merge tool"
    'web-search', // LLM web search, not a PostHog MCP tool
    'comma-separated',
    'skills-store', // the Skills store feature ("the skills-store tools")
    'llma-alerts', // skills-store skill, not in this repo
    'text-embedding-3-small-1536', // embedding model name
    'deep-dive', // "a deep-dive skill"
    'team-shared',
    'per-team',
    'multi-file',
])

// "use the X tool", "load the `X` skill" — kebab or snake candidate followed by tool/skill.
const PHRASE_REFERENCE = /(?<![A-Za-z0-9_`-])`?([a-z0-9]+(?:[_-][a-z0-9]+)+)`?\s+(tools?|skills?)\b/g
// "via `X`", "use `X`" — kebab-only (snake here is usually a field/SDK name, not a tool).
const INVOCATION_REFERENCE =
    /\b(?:via|use|using|call|calling)\s+(?:the\s+)?`([a-z0-9]+(?:-[a-z0-9]+)+)`(?!\s*(?:tools?|skills?)\b)/g
// A noun right after the backticked name means it's not a tool reference ("via the `x` feature flag").
const ENTITY_NOUN_AFTER = /^\s+(?:feature|flag|event|property|properties|column|field|table|key|filter)s?\b/
// Backticked snake_case whose kebab form is a real tool — wrong casing.
const SNAKE_CASE_REFERENCE = /`([a-z0-9]+(?:_[a-z0-9]+)+)`/g

type PhraseReference = { name: string; kind: ReferenceKind }

function findPhraseReferences(text: string): PhraseReference[] {
    return [...text.matchAll(PHRASE_REFERENCE)].map((match) => ({
        name: match[1]!, // both groups always capture on a match
        kind: match[2] as ReferenceKind, // guaranteed by the `(tools?|skills?)` alternation
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

function didYouMean(name: string, toolNames: Set<string>): string {
    const kebab = name.replace(/_/g, '-')
    const matches = [...toolNames].filter((t) => t === kebab || t.endsWith(`-${kebab}`))
    return matches.length > 0 ? ` — did you mean ${matches.join(' or ')}?` : ''
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

    for (const { name, kind } of findPhraseReferences(text)) {
        if (!isValidReference(name, kind, toolNames, skillNames)) {
            report(name, `references nonexistent ${kind.replace(/s$/, '')}${didYouMean(name, toolNames)}`)
        }
    }
    // "via `X`" names one concrete thing but not whether it's a tool or skill: check tools with
    // singular kind (a family prefix like `feature-flag` is not invocable), plus exact skill names.
    for (const name of findInvocationReferences(text)) {
        if (!isValidReference(name, 'tool', toolNames, skillNames) && !skillNames.has(name)) {
            report(name, `references nonexistent tool${didYouMean(name, toolNames)}`)
        }
    }
    for (const name of findBacktickedSnakeCase(text)) {
        if (!toolNames.has(name) && toolNames.has(name.replace(/_/g, '-'))) {
            report(name, `wrong casing — the tool is named ${name.replace(/_/g, '-')}`)
        }
    }
}
