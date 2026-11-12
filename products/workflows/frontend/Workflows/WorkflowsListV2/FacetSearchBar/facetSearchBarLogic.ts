import { MakeLogicType, actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import {
    FacetDefinition,
    FacetFilter,
    FacetSearchValue,
    FacetValueCount,
    MatchesText,
    createFacetCounter,
    facetFilterKey,
    facetNames,
    findFacet,
    formatFacetValue,
    normalizeFacetValue,
    resolvedFacetFilterKey,
    tokenValue,
} from './facetQuery'

const MAX_VALUE_SUGGESTIONS = 50
const MAX_CROSS_FACET_SUGGESTIONS = 8
const MIN_CROSS_FACET_TOKEN_LENGTH = 2
// Enough for the scopes one keystroke reads: the draft's, the one without pills, and the one before it.
const MAX_COUNTED_SCOPES = 4

// The logic serves any item type. The typed `FacetSearchBar` component keeps callers consistent.
/* oxlint-disable @typescript-eslint/no-explicit-any */
export interface FacetSearchBarLogicProps {
    id: string
    facets: FacetDefinition<any>[]
    items: any[]
    value: FacetSearchValue
    onChange: (value: FacetSearchValue) => void
    matchesText: MatchesText<any>
}
/* oxlint-enable @typescript-eslint/no-explicit-any */

interface SuggestionRow {
    id: string
    label: string
    detail?: string
    count?: number
}

export type FacetSuggestion =
    | (SuggestionRow & {
          kind: 'facet'
          /** The input after picking the facet. */
          nextInput: string
      })
    | (SuggestionRow & {
          kind: 'value'
          filter: FacetFilter
          /** The text typed before the value, kept as the search text. */
          rest: string
      })
    | (SuggestionRow & { kind: 'search' | 'none' })

export interface FacetDraft {
    facetKey: string
    facetLabel: string
    negated: boolean
    partial: string
    openQuote: boolean
    /** The input before the draft token. It stays as the free text. */
    rest: string
}

const DRAFT_PATTERN = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"?|(\S*))$/
// A token is complete when whitespace follows it, or when its quoted value is closed.
const COMPLETE_TOKEN = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"|([^\s"]+)(?=\s))/g

/**
 * Answers, for offsets that only grow, whether the input there is inside an open quote, in one scan for all calls.
 * A backslash escapes the next character, as the serializer writes it, so `\\"` still closes a quote.
 */
function createQuoteTracker(input: string): (offset: number) => boolean {
    let index = 0
    let open = false
    return (offset) => {
        for (; index < offset; index++) {
            if (input[index] === '\\') {
                index++
            } else if (input[index] === '"') {
                open = !open
            }
        }
        return open
    }
}

/** Takes every complete, known `facet:value` token out of the input. The rest stays as typed. */
function extractCompleteFilters(
    input: string,
    facets: FacetDefinition<unknown>[]
): { filters: FacetFilter[]; remaining: string } {
    const filters: FacetFilter[] = []
    const isInsideOpenQuote = createQuoteTracker(input)
    const remaining = input.replace(
        COMPLETE_TOKEN,
        (
            token: string,
            lead: string,
            minus: string,
            key: string,
            quoted: string | undefined,
            bare: string | undefined,
            offset: number
        ) => {
            const facet = findFacet(facets, key)
            const value = facet && normalizeFacetValue(facet, tokenValue(quoted, bare))
            // A token inside a quoted value that is still being typed is part of that value.
            if (!facet || !value || isInsideOpenQuote(offset)) {
                return token
            }
            filters.push({ facet: facet.key, value, negated: minus === '-' })
            return lead
        }
    )
    const isInsideQuote = createQuoteTracker(remaining)
    const collapsed = remaining.replace(/\s{2,}/g, (run: string, offset: number) => (isInsideQuote(offset) ? run : ' '))
    return { filters, remaining: collapsed.replace(/^\s+/, '') }
}

function parseFacetDraft(input: string, facets: FacetDefinition<unknown>[]): FacetDraft | null {
    const match = input.match(DRAFT_PATTERN)
    if (!match || match.index === undefined) {
        return null
    }
    const facet = findFacet(facets, match[3])
    if (!facet) {
        return null
    }
    return {
        facetKey: facet.key,
        facetLabel: facet.label,
        negated: match[2] === '-',
        partial: tokenValue(match[4], match[5]),
        openQuote: match[4] !== undefined,
        rest: input.slice(0, match.index + match[1].length),
    }
}

function splitLastToken(input: string): { rest: string; token: string } {
    // A scan, because a regex with a lazy prefix backtracks quadratically on a long pasted token.
    let start = input.length
    while (start > 0 && !/\s/.test(input[start - 1])) {
        start--
    }
    return { rest: input.slice(0, start), token: input.slice(start) }
}

function textOf(input: string, draft: FacetDraft | null): string {
    return (draft ? draft.rest : input).trim()
}

const isFilterRow = (suggestion: FacetSuggestion | null | undefined): boolean =>
    suggestion?.kind === 'facet' || suggestion?.kind === 'value'

const verbOf = (suggestion: FacetSuggestion): string =>
    suggestion.kind === 'facet' ? `pick ${suggestion.label}` : 'add filter'

/** What narrows a draft's values besides its own facet: the free text and the other facets' pills. */
function narrowingOf(draft: FacetDraft, value: FacetSearchValue): string | null {
    const otherFilters = value.filters.some((filter) => filter.facet !== draft.facetKey)
    const search = !!draft.rest.trim()
    if (otherFilters && search) {
        return 'your search and other filters'
    }
    if (otherFilters) {
        return 'your other filters'
    }
    return search ? 'your search' : null
}

function noValuesLabel(draft: FacetDraft, value: FacetSearchValue, freeTextValues: boolean): string {
    const narrowing = narrowingOf(draft, value)
    const within = narrowing ? ` with ${narrowing}` : ''
    if (!draft.partial) {
        return `No values to pick${within}`
    }
    return freeTextValues
        ? `No match for "${draft.partial}"${within}. Press Space to search anyway.`
        : `No value matches "${draft.partial}"${within}`
}

/** Such a space mostly follows a value that committed on its last letter, and separates nothing. */
function isRedundantSpace(previous: string, next: string): boolean {
    return (
        next === `${previous} ` &&
        (previous === '' || /\s$/.test(previous)) &&
        !createQuoteTracker(previous)(previous.length)
    )
}

type FilterChangeSource = 'suggestion' | 'typed' | 'remove button' | 'backspace'

function reportFilterChange(
    searchBar: string,
    change: 'added' | 'removed',
    filter: FacetFilter,
    source: FilterChangeSource
): void {
    posthog.capture('search bar filter changed', {
        search_bar: searchBar,
        change,
        facet: filter.facet,
        negated: filter.negated,
        source,
    })
}

export type CountValuesIn = (scope: FacetSearchValue) => (facetKey: string) => FacetValueCount[]

interface SuggestionSource {
    facets: FacetDefinition<unknown>[]
    value: FacetSearchValue
    countValuesIn: CountValuesIn
}

/** The pill a draft names as if its suggestion were picked: exactly one value, and no other value that starts with the text. */
function filterNamedBy(draft: FacetDraft, { facets, value, countValuesIn }: SuggestionSource): FacetFilter | null {
    if (!draft.partial || draft.openQuote) {
        return null
    }
    const facet = findFacet(facets, draft.facetKey)!
    const typed = draft.partial.toLowerCase()
    const namesOf = (v: string): string[] => [v.toLowerCase(), formatFacetValue(facet, v).toLowerCase()]
    const valuesFor = (scope: FacetSearchValue): string[] => countValuesIn(scope)(facet.key).map(({ value: v }) => v)
    const named = valuesFor({ filters: value.filters, text: draft.rest }).filter((v) => namesOf(v).includes(typed))
    // Values the other pills hide still count, so a pill change never decides what the typing meant.
    const startsAnother = valuesFor({ filters: [], text: '' }).some(
        (v) => !named.includes(v) && namesOf(v).some((name) => name.startsWith(typed))
    )
    if (named.length !== 1 || startsAnother) {
        return null
    }
    const filter = { facet: facet.key, value: named[0], negated: draft.negated }
    const key = resolvedFacetFilterKey(facets, filter)
    return value.filters.some((existing) => resolvedFacetFilterKey(facets, existing) === key) ? null : filter
}

/** The facet's pinned values first, each with its count or 0, then the other values in count order. */
function pinnedFirst(facet: FacetDefinition<unknown>, counts: FacetValueCount[]): FacetValueCount[] {
    const pinnedValues = facet.pinnedValues ?? []
    const isPinned = (v: string): boolean => pinnedValues.some((pinned) => pinned.toLowerCase() === v.toLowerCase())
    const pinned = pinnedValues.map((pinnedValue): FacetValueCount => {
        const resolved = (facet.resolveValue?.(pinnedValue) ?? pinnedValue).toLowerCase()
        return {
            value: pinnedValue,
            count: counts.find(({ value: v }) => v.toLowerCase() === resolved)?.count ?? 0,
        }
    })
    return [...pinned, ...counts.filter(({ value: v }) => !isPinned(v))]
}

function valueSuggestions(
    draft: FacetDraft,
    { facets, value, countValuesIn }: SuggestionSource,
    chosen: Set<string>
): FacetSuggestion[] {
    const facet = findFacet(facets, draft.facetKey)!
    const partial = draft.partial.toLowerCase()
    const counts = countValuesIn({ filters: value.filters, text: draft.rest })(facet.key)
    const rows: FacetSuggestion[] = []
    let firstChosenLabel: string | null = null
    for (const { value: v, count } of pinnedFirst(facet, counts)) {
        if (rows.length === MAX_VALUE_SUGGESTIONS) {
            break
        }
        const label = formatFacetValue(facet, v)
        if (partial && !label.toLowerCase().includes(partial) && !v.toLowerCase().includes(partial)) {
            continue
        }
        const filter = { facet: facet.key, value: v, negated: draft.negated }
        if (chosen.has(resolvedFacetFilterKey(facets, filter))) {
            firstChosenLabel ??= label
            continue
        }
        rows.push({
            id: `value-${facet.key}-${v}`,
            kind: 'value',
            label: `${draft.negated ? 'Not ' : ''}${label}`,
            detail: draft.negated ? `Hides ${count}` : undefined,
            count: draft.negated ? undefined : count,
            filter,
            rest: draft.rest,
        })
    }
    if (rows.length) {
        return rows
    }
    const label =
        counts.length === 0 && facet.emptyLabel
            ? facet.emptyLabel
            : firstChosenLabel !== null
              ? `${firstChosenLabel} is already a filter`
              : noValuesLabel(draft, value, !!facet.freeTextValues)
    return [{ id: 'none', kind: 'none', label }]
}

function facetNameSuggestions(
    facets: FacetDefinition<unknown>[],
    rest: string,
    bare: string,
    negated: boolean
): FacetSuggestion[] {
    const prefix = negated ? '-' : ''
    return facets
        .filter((facet) => [...facetNames(facet), facet.label.toLowerCase()].some((name) => name.startsWith(bare)))
        .map(
            (facet): FacetSuggestion => ({
                id: `facet-${facet.key}`,
                kind: 'facet',
                label: `${prefix}${facet.key}:`,
                detail: facet.description,
                nextInput: `${rest}${prefix}${facet.key}:`,
            })
        )
}

function crossFacetSuggestions(
    rest: string,
    bare: string,
    negated: boolean,
    { facets, value, countValuesIn }: SuggestionSource,
    chosen: Set<string>
): FacetSuggestion[] {
    const matches: FacetSuggestion[] = []
    const countValues = countValuesIn({ filters: value.filters, text: rest })
    for (const facet of facets) {
        for (const { value: v, count } of countValues(facet.key)) {
            if (matches.length === MAX_CROSS_FACET_SUGGESTIONS) {
                return matches
            }
            const label = formatFacetValue(facet, v)
            if (!label.toLowerCase().includes(bare) && !v.toLowerCase().includes(bare)) {
                continue
            }
            const filter = { facet: facet.key, value: v, negated }
            if (chosen.has(resolvedFacetFilterKey(facets, filter))) {
                continue
            }
            matches.push({
                id: `value-${facet.key}-${v}`,
                kind: 'value',
                label: `${negated ? 'Not ' : ''}${facet.label}: ${label}`,
                count,
                filter,
                rest,
            })
        }
    }
    return matches
}

function buildSuggestions(input: string, draft: FacetDraft | null, source: SuggestionSource): FacetSuggestion[] {
    const { facets, value } = source
    const chosen = new Set(value.filters.map((filter) => resolvedFacetFilterKey(facets, filter)))
    if (draft) {
        return valueSuggestions(draft, source, chosen)
    }

    const { rest, token } = splitLastToken(input)
    if (!token) {
        return facets
            .filter((facet) => facet.showOnFocus)
            .map(
                (facet): FacetSuggestion => ({
                    id: `facet-${facet.key}`,
                    kind: 'facet',
                    label: `${facet.key}:`,
                    detail: facet.description,
                    nextInput: `${input}${facet.key}:`,
                })
            )
    }

    const negated = token.startsWith('-')
    const bare = (negated ? token.slice(1) : token).toLowerCase()
    return [
        ...(bare ? facetNameSuggestions(facets, rest, bare, negated) : []),
        { id: 'search', kind: 'search', label: `Search for "${input.trim()}"` },
        ...(bare.length >= MIN_CROSS_FACET_TOKEN_LENGTH
            ? crossFacetSuggestions(rest, bare, negated, source, chosen)
            : []),
    ]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicValues {
    composing: boolean
    countValuesIn: CountValuesIn
    draft: FacetDraft | null
    highlightedIndex: number
    highlightedSuggestion: FacetSuggestion | null
    hints: string[]
    input: string
    open: boolean
    rawHighlightedIndex: number
    suggestions: FacetSuggestion[]
    tabTarget: FacetSuggestion | null
    title: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicActions {
    applyHighlighted: () => {
        value: true
    }
    applySuggestion: (suggestion: FacetSuggestion) => {
        suggestion: FacetSuggestion
    }
    applyTabTarget: () => {
        value: true
    }
    moveHighlight: (delta: number) => {
        delta: number
    }
    removeFilter: (filter: FacetFilter) => {
        filter: FacetFilter
    }
    removeLastFilter: () => {
        value: true
    }
    setComposing: (
        composing: boolean,
        caret?: number
    ) => {
        caret: number | undefined
        composing: boolean
    }
    setHighlightedIndex: (index: number) => {
        index: number
    }
    setInput: (
        input: string,
        caret?: number
    ) => {
        caret: number
        input: string
    }
    setOpen: (open: boolean) => {
        open: boolean
    }
    syncInput: (input: string) => {
        input: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        countValuesIn: (items: any[], facets: FacetDefinition<any>[], matchesText: MatchesText<any>) => CountValuesIn
        draft: (input: string, facets: FacetDefinition<any>[]) => FacetDraft | null
        suggestions: (
            input: string,
            draft: FacetDraft | null,
            facets: FacetDefinition<any>[],
            value: FacetSearchValue,
            countValuesIn: CountValuesIn
        ) => FacetSuggestion[]
        highlightedIndex: (rawHighlightedIndex: number, suggestions: FacetSuggestion[]) => number
        highlightedSuggestion: (suggestions: FacetSuggestion[], highlightedIndex: number) => FacetSuggestion | null
        tabTarget: (
            input: string,
            suggestions: FacetSuggestion[],
            highlightedSuggestion: FacetSuggestion | null
        ) => FacetSuggestion | null
        title: (input: string, draft: FacetDraft | null) => string
        hints: (highlightedSuggestion: FacetSuggestion | null, tabTarget: FacetSuggestion | null) => string[]
    }
}

export type facetSearchBarLogicType = MakeLogicType<
    facetSearchBarLogicValues,
    facetSearchBarLogicActions,
    FacetSearchBarLogicProps,
    facetSearchBarLogicMeta
>

export const facetSearchBarLogic = kea<facetSearchBarLogicType>([
    props({} as FacetSearchBarLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'workflows', 'frontend', 'facetSearchBarLogic', key]),
    actions({
        setInput: (input: string, caret?: number) => ({ input, caret: caret ?? input.length }),
        syncInput: (input: string) => ({ input }),
        setOpen: (open: boolean) => ({ open }),
        setComposing: (composing: boolean, caret?: number) => ({ composing, caret }),
        setHighlightedIndex: (index: number) => ({ index }),
        moveHighlight: (delta: number) => ({ delta }),
        applySuggestion: (suggestion: FacetSuggestion) => ({ suggestion }),
        applyHighlighted: true,
        applyTabTarget: true,
        removeFilter: (filter: FacetFilter) => ({ filter }),
        removeLastFilter: true,
    }),
    reducers(({ props }) => ({
        input: [
            (props.value?.text ?? '') as string,
            {
                setInput: (state, { input, caret }) =>
                    caret === input.length && isRedundantSpace(state, input) ? state : input,
                syncInput: (_, { input }) => input,
            },
        ],
        composing: [
            false,
            {
                setComposing: (_, { composing }) => composing,
            },
        ],
        open: [
            false,
            {
                setOpen: (_, { open }) => open,
                setInput: () => true,
            },
        ],
        rawHighlightedIndex: [
            0,
            {
                setHighlightedIndex: (_, { index }) => index,
                setInput: () => 0,
                syncInput: () => 0,
                setOpen: () => 0,
            },
        ],
    })),
    selectors({
        countValuesIn: [
            (_, p) => [p.items, p.facets, p.matchesText],
            (items: any[], facets: FacetDefinition<any>[], matchesText: MatchesText<any>): CountValuesIn => {
                // Typing a value keeps its scope, so each keystroke reuses the counts instead of walking every item.
                const counters = new Map<string, (facetKey: string) => FacetValueCount[]>()
                return (scope) => {
                    const key = JSON.stringify([
                        scope.filters.map((filter) => facetFilterKey(filter, facets)),
                        scope.text.trim(),
                    ])
                    let counter = counters.get(key)
                    if (!counter) {
                        counter = createFacetCounter(items, scope, facets, matchesText)
                        counters.set(key, counter)
                        if (counters.size > MAX_COUNTED_SCOPES) {
                            counters.delete(counters.keys().next().value!)
                        }
                    }
                    return counter
                }
            },
        ],
        draft: [
            (s, p) => [s.input, p.facets],
            (input: string, facets: FacetDefinition<unknown>[]): FacetDraft | null => parseFacetDraft(input, facets),
        ],
        suggestions: [
            (s, p) => [s.input, s.draft, p.facets, p.value, s.countValuesIn],
            (
                input: string,
                draft: FacetDraft | null,
                facets: FacetDefinition<any>[],
                value: FacetSearchValue,
                countValuesIn: CountValuesIn
            ): FacetSuggestion[] => buildSuggestions(input, draft, { facets, value, countValuesIn }),
        ],
        highlightedIndex: [
            (s) => [s.rawHighlightedIndex, s.suggestions],
            (raw: number, suggestions: FacetSuggestion[]): number => Math.max(0, Math.min(raw, suggestions.length - 1)),
        ],
        highlightedSuggestion: [
            (s) => [s.suggestions, s.highlightedIndex],
            (suggestions: FacetSuggestion[], index: number): FacetSuggestion | null =>
                suggestions[index]?.kind === 'none' ? null : (suggestions[index] ?? null),
        ],
        tabTarget: [
            (s) => [s.input, s.suggestions, s.highlightedSuggestion],
            (
                input: string,
                suggestions: FacetSuggestion[],
                highlighted: FacetSuggestion | null
            ): FacetSuggestion | null => {
                // Tab and → never run a plain search. With an empty input, Tab moves focus as usual.
                if (!input.trim()) {
                    return null
                }
                return isFilterRow(highlighted) ? highlighted : (suggestions.find(isFilterRow) ?? null)
            },
        ],
        title: [
            (s) => [s.input, s.draft],
            (input: string, draft: FacetDraft | null): string =>
                draft
                    ? `${draft.facetLabel}${draft.negated ? ' is not' : ''}`
                    : input.trim()
                      ? 'Search or filter'
                      : 'Filter by',
        ],
        hints: [
            (s) => [s.highlightedSuggestion, s.tabTarget],
            (highlighted: FacetSuggestion | null, tabTarget: FacetSuggestion | null): string[] => {
                const hints: string[] = []
                if (highlighted?.kind === 'search') {
                    hints.push('Enter to search')
                } else if (highlighted && isFilterRow(highlighted)) {
                    hints.push(`Enter${tabTarget === highlighted ? ' or Tab' : ''} to ${verbOf(highlighted)}`)
                }
                if (tabTarget && tabTarget !== highlighted) {
                    hints.push(`Tab or → to ${verbOf(tabTarget)}`)
                }
                return [...hints, '↑↓ to move', 'Esc to close']
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        setInput: ({ caret }) => {
            const input = values.input
            // Typed or pasted `facet:value` tokens become pills as soon as they are complete. An input method may
            // still change the value, so during a composition nothing becomes a pill until it ends.
            const { filters, remaining } = values.composing
                ? { filters: [], remaining: input }
                : extractCompleteFilters(input, props.facets)
            const known = new Set(props.value.filters.map((filter) => resolvedFacetFilterKey(props.facets, filter)))
            const added = filters.filter((filter) => {
                const key = resolvedFacetFilterKey(props.facets, filter)
                // A pasted query can repeat a token; each pill is added once.
                if (known.has(key)) {
                    return false
                }
                known.add(key)
                return true
            })
            let nextInput = filters.length ? remaining : input
            let draft = parseFacetDraft(nextInput, props.facets)
            // A value corrected in its middle is still being typed.
            const named =
                draft && !values.composing && caret >= input.length
                    ? filterNamedBy(draft, {
                          facets: props.facets,
                          value: { ...props.value, filters: [...props.value.filters, ...added] },
                          countValuesIn: values.countValuesIn,
                      })
                    : null
            if (draft && named) {
                added.push(named)
                nextInput = draft.rest.trim() ? `${draft.rest.trimEnd()} ` : ''
                draft = null
            }
            const text = textOf(nextInput, draft)
            if (nextInput !== input) {
                actions.syncInput(nextInput)
            }
            if (added.length || text !== props.value.text) {
                props.onChange({ filters: [...props.value.filters, ...added], text })
            }
            for (const filter of added) {
                reportFilterChange(props.id, 'added', filter, 'typed')
            }
        },
        setComposing: ({ composing, caret }) => {
            if (!composing) {
                actions.setInput(values.input, caret)
            }
        },
        moveHighlight: ({ delta }) => {
            const last = Math.max(0, values.suggestions.length - 1)
            actions.setHighlightedIndex(Math.max(0, Math.min(values.highlightedIndex + delta, last)))
        },
        applySuggestion: ({ suggestion }) => {
            if (suggestion.kind === 'facet') {
                actions.setInput(suggestion.nextInput)
            } else if (suggestion.kind === 'value') {
                const rest = suggestion.rest.trimEnd()
                props.onChange({ filters: [...props.value.filters, suggestion.filter], text: rest.trim() })
                reportFilterChange(props.id, 'added', suggestion.filter, 'suggestion')
                actions.syncInput(rest ? `${rest} ` : '')
                actions.setOpen(true)
            } else {
                actions.setOpen(false)
            }
        },
        applyHighlighted: () => {
            if (values.highlightedSuggestion) {
                actions.applySuggestion(values.highlightedSuggestion)
            }
        },
        applyTabTarget: () => {
            if (values.tabTarget) {
                actions.applySuggestion(values.tabTarget)
            }
        },
        removeFilter: ({ filter }) => {
            const removed = facetFilterKey(filter, props.facets)
            props.onChange({
                filters: props.value.filters.filter((f) => facetFilterKey(f, props.facets) !== removed),
                text: props.value.text,
            })
            reportFilterChange(props.id, 'removed', filter, 'remove button')
        },
        removeLastFilter: () => {
            const last = props.value.filters.at(-1)
            if (last) {
                props.onChange({ filters: props.value.filters.slice(0, -1), text: props.value.text })
                reportFilterChange(props.id, 'removed', last, 'backspace')
            }
        },
    })),
    propsChanged(({ actions, values, props }) => {
        // The URL or a "Clear filters" button can change the text without this input.
        if (props.value.text !== textOf(values.input, values.draft)) {
            actions.syncInput(props.value.text)
        }
    }),
])
