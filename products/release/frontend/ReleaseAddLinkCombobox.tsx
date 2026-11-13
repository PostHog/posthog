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
import { LinkCandidate, ReleaseRow } from './releaseUtils'

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
    const linkSuggestions = linkSuggestionsFor === linkSuggestionsKey(row) ? loadedSuggestions : []
    const linkSearchResults = linkSearchFailed ? [] : loadedResults
    const linked = new Set([
        ...row.flags.map((flag) => `flag:${flag.id}`),
        ...row.broadcasts.map((broadcast) => `broadcast:${broadcast.id}`),
    ])
    const candidates = new Map<string, LinkCandidate>()
    for (const candidate of [...linkSuggestions, ...linkSearchResults]) {
        if (!linked.has(candidate.key)) {
            candidates.set(candidate.key, candidate)
        }
    }
    const suggested = linkSuggestions.filter((candidate) => candidates.has(candidate.key)).map((item) => item.key)
    const shown = new Set(suggested)
    const available = (kind: LinkCandidate['kind']): string[] =>
        linkSearchResults
            .filter((item) => item.kind === kind && candidates.has(item.key) && !shown.has(item.key))
            .map((item) => item.key)
    const groups: CandidateGroup[] = [
        { key: 'suggested', label: 'Suggested', items: suggested },
        { key: 'flags', label: 'Feature flags', items: available('flag') },
        { key: 'broadcasts', label: 'Broadcasts', items: available('broadcast') },
    ].filter((group) => group.items.length)

    return (
        <Combobox
            items={groups}
            filter={null}
            value={null}
            onOpenChange={(open: boolean) => open && searchLinks('')}
            onInputValueChange={(value: string) => searchLinks(value)}
            onValueChange={(key: string | null) => {
                const candidate = key ? candidates.get(key) : undefined
                if (candidate) {
                    addLink(row.id, candidate)
                }
            }}
            itemToStringLabel={(key: string) => candidates.get(key)?.label ?? ''}
        >
            <ComboboxInput
                placeholder="Add a flag or broadcast"
                aria-label="Add a flag or broadcast to the release"
                data-attr="release-add-link"
            />
            <ComboboxContent>
                <ComboboxEmpty>
                    {linkSearchResultsLoading ? (
                        <Spinner />
                    ) : linkSearchFailed ? null : (
                        'No flag or broadcast matches that name.'
                    )}
                </ComboboxEmpty>
                {linkSearchFailed && !linkSearchResultsLoading && (
                    <div className="flex flex-col items-center gap-2 px-2 py-2">
                        <Text size="xs">Search could not load. Check your connection, then try again.</Text>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() => searchLinks(lastLinkSearch)}
                            data-attr="release-add-link-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                {linkSearchIncomplete && !linkSearchResultsLoading && (
                    <div className="flex items-center justify-between gap-2 px-2 py-1">
                        <Text size="xs" variant="muted">
                            Some results could not load.
                        </Text>
                        <Button
                            size="xs"
                            variant="link-muted"
                            onClick={() => searchLinks(lastLinkSearch)}
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
                                                {iconForType(
                                                    candidate?.kind === 'flag' ? 'feature_flag' : 'broadcasts'
                                                )}
                                            </span>
                                            <span
                                                className={
                                                    candidate?.kind === 'flag' ? 'truncate font-mono' : 'truncate'
                                                }
                                            >
                                                {candidate?.label}
                                            </span>
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
