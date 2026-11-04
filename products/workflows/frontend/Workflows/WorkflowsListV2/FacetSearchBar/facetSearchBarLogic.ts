import { MakeLogicType, actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import {
    FacetDefinition,
    FacetFilter,
    FacetSearchValue,
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
          /** The pill to add. */
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

/** Takes every complete, known `facet:value` token out of the input. The rest stays as typed. */
function extractCompleteFilters(
    input: string,
    facets: FacetDefinition<unknown>[]
): { filters: FacetFilter[]; remaining: string } {
    const filters: FacetFilter[] = []
    const remaining = input.replace(
        COMPLETE_TOKEN,
        (token: string, lead: string, minus: string, key: string, quoted?: string, bare?: string) => {
            const facet = findFacet(facets, key)
            const value = facet && normalizeFacetValue(facet, tokenValue(quoted, bare))
            if (!facet || !value) {
                return token
            }
            filters.push({ facet: facet.key, value, negated: minus === '-' })
            return lead
        }
    )
    return { filters, remaining: remaining.replace(/\s{2,}/g, ' ').replace(/^\s+/, '') }
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
    return next === `${previous} ` && (previous === '' || /\s$/.test(previous))
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

type SuggestionSource = Pick<FacetSearchBarLogicProps, 'facets' | 'items' | 'value' | 'matchesText'>

/** The pill a draft names as if its suggestion were picked: exactly one value, and no other value that starts with the text. */
function filterNamedBy(draft: FacetDraft, { facets, items, value, matchesText }: SuggestionSource): FacetFilter | null {
    if (!draft.partial || draft.openQuote) {
        return null
    }
    const facet = findFacet(facets, draft.facetKey)!
    const comparable = (text: string): string => (facet.caseSensitive ? text : text.toLowerCase())
    const typed = comparable(draft.partial)
    const namesOf = (v: string): string[] => [comparable(v), comparable(formatFacetValue(facet, v))]
    const valuesFor = (scope: FacetSearchValue): string[] =>
        createFacetCounter(items, scope, facets, matchesText)(facet.key).map(({ value: v }) => v)
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

function buildSuggestions(
    input: string,
    draft: FacetDraft | null,
    { facets, items, value, matchesText }: SuggestionSource
): FacetSuggestion[] {
    const chosen = new Set(value.filters.map((filter) => resolvedFacetFilterKey(facets, filter)))

    if (draft) {
        const facet = findFacet(facets, draft.facetKey)!
        const partial = draft.partial.toLowerCase()
        const counts = createFacetCounter(
            items,
            { filters: value.filters, text: draft.rest },
            facets,
            matchesText
        )(facet.key)
        const matching = counts.filter(({ value: v }) => {
            const label = formatFacetValue(facet, v).toLowerCase()
            return !partial || label.includes(partial) || v.toLowerCase().includes(partial)
        })
        const isChosen = (v: string): boolean =>
            chosen.has(resolvedFacetFilterKey(facets, { facet: facet.key, value: v, negated: draft.negated }))
        const rows = matching
            .filter(({ value: v }) => !isChosen(v))
            .slice(0, MAX_VALUE_SUGGESTIONS)
            .map(
                ({ value: v, count }): FacetSuggestion => ({
                    id: `value-${facet.key}-${v}`,
                    kind: 'value',
                    label: `${draft.negated ? 'Not ' : ''}${formatFacetValue(facet, v)}`,
                    detail: draft.negated ? `Hides ${count}` : undefined,
                    count: draft.negated ? undefined : count,
                    filter: { facet: facet.key, value: v, negated: draft.negated },
                    rest: draft.rest,
                })
            )
        if (rows.length) {
            return rows
        }
        const label =
            counts.length === 0 && facet.emptyLabel
                ? facet.emptyLabel
                : matching.length
                  ? `${formatFacetValue(facet, matching[0].value)} is already a filter`
                  : noValuesLabel(draft, value, !!facet.freeTextValues)
        return [{ id: 'none', kind: 'none', label }]
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
    const result: FacetSuggestion[] = []
    if (bare) {
        for (const facet of facets) {
            if ([...facetNames(facet), facet.label.toLowerCase()].some((name) => name.startsWith(bare))) {
                result.push({
                    id: `facet-${facet.key}`,
                    kind: 'facet',
                    label: `${negated ? '-' : ''}${facet.key}:`,
                    detail: facet.description,
                    nextInput: `${rest}${negated ? '-' : ''}${facet.key}:`,
                })
            }
        }
    }
    result.push({ id: 'search', kind: 'search', label: `Search for "${input.trim()}"` })

    if (bare.length >= MIN_CROSS_FACET_TOKEN_LENGTH) {
        const matches: FacetSuggestion[] = []
        const countValues = createFacetCounter(items, { filters: value.filters, text: rest }, facets, matchesText)
        for (const facet of facets) {
            for (const { value: v, count } of countValues(facet.key)) {
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
        result.push(...matches.slice(0, MAX_CROSS_FACET_SUGGESTIONS))
    }
    return result
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicValues {
    composing: boolean
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
        draft: (input: string, facets: FacetDefinition<any>[]) => FacetDraft | null
        suggestions: (
            input: string,
            draft: FacetDraft | null,
            facets: FacetDefinition<any>[],
            items: any[],
            value: FacetSearchValue,
            matchesText: MatchesText<any>
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
        draft: [
            (s, p) => [s.input, p.facets],
            (input: string, facets: FacetDefinition<unknown>[]): FacetDraft | null => parseFacetDraft(input, facets),
        ],
        suggestions: [
            (s, p) => [s.input, s.draft, p.facets, p.items, p.value, p.matchesText],
            (
                input: string,
                draft: FacetDraft | null,
                facets: FacetDefinition<any>[],
                items: any[],
                value: FacetSearchValue,
                matchesText: MatchesText<any>
            ): FacetSuggestion[] => buildSuggestions(input, draft, { facets, items, value, matchesText }),
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
                          ...props,
                          value: { ...props.value, filters: [...props.value.filters, ...added] },
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
