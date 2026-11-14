import { useActions, useValues } from 'kea'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    Spinner,
    Text,
} from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { linkSuggestionsKey, releaseLogic } from './releaseLogic'
import { RelatedKind, releaseRelatedLogic } from './releaseRelatedLogic'
import { linkedKeys } from './releaseTracks'
import { LinkCandidate, ReleaseRow } from './releaseUtils'

interface Option {
    key: string
    kind: LinkCandidate['kind'] | RelatedKind
    label: string
    add: () => void
}

const OPTION_ICON = {
    flag: 'feature_flag',
    broadcast: 'broadcasts',
    survey: 'survey',
    insight: 'insight/trends',
} as const

interface CandidateGroup {
    key: string
    label: string
    items: string[]
}

export function ReleaseAddLinkCombobox({ row }: { row: ReleaseRow }): JSX.Element {
    const {
        linkSearchResults: loadedResults,
        linkSearchResultsLoading,
        linkSuggestions: loadedSuggestions,
        linkSuggestionsFor,
        linkSearchFailed,
        linkSearchIncomplete,
        lastLinkSearch,
    } = useValues(releaseLogic)
    const { searchLinks, addLink } = useActions(releaseLogic)
    const { relatedSearch, relatedSearchLoading, relatedByRelease, lastRelatedSearch } = useValues(releaseRelatedLogic)
    const { searchRelated, linkRelated } = useActions(releaseRelatedLogic)
    const retry = (): void => {
        searchLinks(lastLinkSearch)
        searchRelated(lastRelatedSearch)
    }
    const searching = linkSearchResultsLoading || relatedSearchLoading
    const related = relatedByRelease[row.id]
    const linkSuggestions = linkSuggestionsFor === linkSuggestionsKey(row) ? loadedSuggestions : []
    const linkSearchResults = linkSearchFailed ? [] : loadedResults
    const linked = linkedKeys(row, related)
    const candidates = new Map<string, Option>()
    for (const candidate of [...linkSuggestions, ...linkSearchResults]) {
        if (!linked.has(candidate.key)) {
            candidates.set(candidate.key, { ...candidate, add: () => addLink(row.id, candidate) })
        }
    }
    for (const survey of relatedSearch.surveys) {
        const key = `survey:${survey.id}`
        if (!linked.has(key)) {
            candidates.set(key, {
                key,
                kind: 'survey',
                label: survey.name,
                add: () => linkRelated(row.id, 'survey', survey.id),
            })
        }
    }
    for (const insight of relatedSearch.insights) {
        const key = `insight:${insight.id}`
        if (!linked.has(key)) {
            candidates.set(key, {
                key,
                kind: 'insight',
                label: insight.name,
                add: () => linkRelated(row.id, 'insight', String(insight.id)),
            })
        }
    }
    const suggested = linkSuggestions.filter((candidate) => candidates.has(candidate.key)).map((item) => item.key)
    const shown = new Set(suggested)
    const available = (kind: Option['kind']): string[] =>
        [...candidates.values()]
            .filter((item) => item.kind === kind && !shown.has(item.key))
            .map((item) => item.key)
            .slice(0, 5)
    const groups: CandidateGroup[] = [
        { key: 'suggested', label: 'Suggested', items: suggested },
        { key: 'flags', label: 'Feature flags', items: available('flag') },
        { key: 'broadcasts', label: 'Broadcasts', items: available('broadcast') },
        { key: 'surveys', label: 'Surveys', items: available('survey') },
        { key: 'insights', label: 'Insights', items: available('insight') },
    ].filter((group) => group.items.length)

    return (
        <Combobox
            items={groups}
            filter={null}
            value={null}
            onOpenChange={(open: boolean) => {
                if (open) {
                    searchLinks('')
                    searchRelated('')
                }
            }}
            onInputValueChange={(value: string) => {
                searchLinks(value)
                searchRelated(value)
            }}
            onValueChange={(key: string | null) => {
                const candidate = key ? candidates.get(key) : undefined
                candidate?.add()
            }}
            itemToStringLabel={(key: string) => candidates.get(key)?.label ?? ''}
        >
            <ComboboxInput
                placeholder="Add a flag, survey, insight or broadcast"
                aria-label="Add a flag, survey, insight or broadcast to the release"
                data-attr="release-add-link"
            />
            <ComboboxContent>
                <ComboboxEmpty>
                    {linkSearchResultsLoading || relatedSearchLoading ? (
                        <Spinner />
                    ) : linkSearchFailed || relatedSearch.failed ? null : (
                        'Nothing matches that name.'
                    )}
                </ComboboxEmpty>
                {linkSearchFailed && !searching && (
                    <div className="flex flex-col items-center gap-2 px-2 py-2">
                        <Text size="xs">Search could not load. Check your connection, then try again.</Text>
                        <Button size="sm" variant="outline" onClick={retry} data-attr="release-add-link-retry">
                            Try again
                        </Button>
                    </div>
                )}
                {(linkSearchIncomplete || (relatedSearch.failed && !linkSearchFailed)) && !searching && (
                    <div className="flex items-center justify-between gap-2 px-2 py-1">
                        <Text size="xs" variant="muted">
                            Some results could not load.
                        </Text>
                        <Button
                            size="xs"
                            variant="link-muted"
                            onClick={retry}
                            data-attr="release-add-link-retry-partial"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                <ComboboxList>
                    {(group: CandidateGroup) => (
                        <ComboboxGroup key={group.key} items={group.items}>
                            <ComboboxLabel>{group.label}</ComboboxLabel>
                            <ComboboxCollection>
                                {(key: string) => {
                                    const candidate = candidates.get(key)
                                    return (
                                        <ComboboxItem key={key} value={key} data-attr="release-add-link-option">
                                            <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
                                                {iconForType(OPTION_ICON[candidate?.kind ?? 'flag'])}
                                            </span>
                                            <span className="truncate">{candidate?.label}</span>
                                        </ComboboxItem>
                                    )
                                }}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
