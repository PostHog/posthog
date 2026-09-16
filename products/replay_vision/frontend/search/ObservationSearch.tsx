import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconClock, IconPlusSmall, IconSearch, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, Popover, Spinner } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { visionScannersListLogic } from '../logics/visionScannersListLogic'
import type { ReplayScanner } from '../replay_scanners/types'
import { type ObservationSearchLogicProps, observationSearchLogic } from './observationSearchLogic'
import { ScannerScopeSelect } from './ScannerScopeSelect'
import { SearchResults } from './SearchResults'

const FALLBACK_EXAMPLE_QUERIES = ['users who got stuck and gave up', 'rage clicking out of frustration']

function exampleQueries(scanner: ReplayScanner | null): string[] {
    switch (scanner?.scanner_type) {
        case 'monitor':
            return ['the most severe cases', 'sessions where the user recovered']
        case 'classifier': {
            const categories = scanner.scanner_config.tags.filter((tag) => tag.trim())
            return categories.length > 0 ? categories.slice(0, 3) : FALLBACK_EXAMPLE_QUERIES
        }
        case 'scorer':
            return ['sessions that struggled the most', 'sessions that went smoothly']
        case 'summarizer':
            return ['users who completed what they came to do', 'confusion and backtracking']
        default:
            return FALLBACK_EXAMPLE_QUERIES
    }
}

function SearchPalette({
    recents,
    suggestions,
    suggestionsLoading,
    disabledReason,
    onPick,
}: {
    recents: string[]
    suggestions: string[]
    suggestionsLoading: boolean
    disabledReason?: string
    onPick: (query: string) => void
}): JSX.Element {
    const item = (query: string, icon: JSX.Element, dataAttr: string): JSX.Element => (
        <LemonButton
            key={query}
            fullWidth
            size="small"
            icon={icon}
            disabledReason={disabledReason}
            // Mouse down would blur the input and close the palette first.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(query)}
            data-attr={dataAttr}
        >
            <span className="truncate">{query}</span>
        </LemonButton>
    )
    return (
        <div className="flex flex-col gap-0.5 p-1" data-attr="vision-search-palette">
            {recents.length > 0 && (
                <>
                    <span className="text-xs text-tertiary font-medium px-2 pt-1">Recent</span>
                    <ul data-attr="vision-search-recent-list">
                        {recents.map((recent) => (
                            <li key={recent}>{item(recent, <IconClock />, 'vision-search-recent')}</li>
                        ))}
                    </ul>
                </>
            )}
            <span className="text-xs text-tertiary font-medium px-2 pt-1">Suggested searches</span>
            {suggestionsLoading ? (
                <Spinner className="self-center my-2" />
            ) : suggestions.length === 0 ? (
                <span className="text-xs text-tertiary px-2 py-1">
                    Themes from what your scanners observed will appear here.
                </span>
            ) : (
                suggestions.map((suggestion) =>
                    item(suggestion, <IconSparkles className="text-accent" />, 'vision-search-example')
                )
            )}
        </div>
    )
}

export function ObservationSearch({ className }: { className?: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { scanners } = useValues(visionScannersListLogic)
    const logicProps: ObservationSearchLogicProps = { teamId: currentTeamId, userId: user?.uuid ?? null }
    const logic = observationSearchLogic(logicProps)
    const {
        query,
        scannerId,
        results,
        searching,
        searchedQuery,
        sourceObservationId,
        recentQueries,
        suggestedQueries,
        suggestedQueriesLoading,
    } = useValues(logic)
    const { setQuery, setScannerId, search, clearSearch } = useActions(logic)

    const [paletteOpen, setPaletteOpen] = useState(false)

    const selectedScanner = (scanners.find((scanner) => scanner.id === scannerId) as ReplayScanner | undefined) ?? null
    const suggestions = suggestedQueries.length > 0 ? suggestedQueries : exampleQueries(selectedScanner)
    const typed = query.trim().toLowerCase()
    const matchingRecents = recentQueries.filter((recent) => recent !== query && recent.toLowerCase().includes(typed))
    const consentReason = dataProcessingAccepted ? undefined : 'AI data processing is turned off for your organization'
    const idle = results === null && !searching
    const canSubmit = dataProcessingAccepted && !searching && !!query.trim()
    const runQuery = (value: string): void => {
        if (searching) {
            return
        }
        setPaletteOpen(false)
        setQuery(value)
        search()
    }
    const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        if (event.nativeEvent.isComposing) {
            return
        }
        if (event.key === 'Escape') {
            setPaletteOpen(false)
        } else if (event.key === 'Enter' && canSubmit) {
            setPaletteOpen(false)
            search()
        }
    }

    const palette = (
        <SearchPalette
            recents={matchingRecents}
            suggestions={suggestions}
            suggestionsLoading={suggestedQueriesLoading}
            disabledReason={consentReason}
            onPick={runQuery}
        />
    )
    const input = (
        <LemonInput
            fullWidth
            size={idle ? 'large' : 'medium'}
            value={query}
            onChange={(value) => {
                setQuery(value)
                setPaletteOpen(true)
            }}
            onFocus={() => setPaletteOpen(true)}
            onBlur={() => setPaletteOpen(false)}
            onKeyDown={onKeyDown}
            placeholder="Describe what to look for"
            disabledReason={consentReason}
            autoComplete="off"
            autoFocus={idle}
            data-attr="vision-search-query"
            prefix={<IconSearch className="text-tertiary" />}
            suffix={
                <>
                    {query && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={clearSearch}
                            tooltip="Clear"
                            data-attr="vision-search-clear"
                        />
                    )}
                    {/* The input chrome focuses the field on click, which opens the palette over the picker. */}
                    <span onClick={(event) => event.stopPropagation()}>
                        <ScannerScopeSelect scanners={scanners} value={scannerId} onChange={setScannerId} />
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={search}
                        loading={searching}
                        disabledReason={
                            consentReason ?? (!query.trim() ? 'Describe what to look for first' : undefined)
                        }
                        data-attr="vision-search-submit"
                    >
                        Search
                    </LemonButton>
                </>
            }
        />
    )

    return (
        <div className={clsx('@container flex flex-col gap-4', className)} data-attr="vision-search">
            {idle && (
                <div className="flex flex-col items-center gap-3 pt-8">
                    <h2 className="text-xl font-semibold m-0">What happened in your sessions?</h2>
                    <span className="text-sm text-secondary">
                        Describe a behavior in plain words. Results are ranked by how well they match.
                    </span>
                </div>
            )}
            {/* One subtree for both states, so the input keeps focus and state when the first results land. */}
            <div className={clsx('flex flex-col gap-2', idle && 'w-full max-w-3xl self-center')}>
                <Popover
                    visible={!idle && paletteOpen && dataProcessingAccepted}
                    onClickOutside={() => setPaletteOpen(false)}
                    placement="bottom-start"
                    matchWidth
                    padded={false}
                    overlay={palette}
                >
                    {input}
                </Popover>
                {idle && <div className="border border-primary rounded-lg bg-surface-primary">{palette}</div>}
            </div>
            {results === null && searching && (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <Spinner /> Searching…
                </div>
            )}
            {results?.length === 0 && (
                <div className="rounded bg-surface-secondary px-3 py-3 flex flex-col gap-3">
                    <div className="text-sm text-secondary">
                        {scannerId
                            ? `No matches in ${selectedScanner?.name ?? 'this scanner'} for "${searchedQuery}".`
                            : `No matches for "${searchedQuery}". Only sessions a scanner has analyzed are searchable, so nothing found can also mean no scanner is watching for this yet.`}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {scannerId ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSearch />}
                                onClick={() => setScannerId(null)}
                                data-attr="vision-search-all-scanners"
                            >
                                Search all scanners
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlusSmall />}
                                to={
                                    combineUrl(
                                        urls.replayVisionTemplates(),
                                        searchedQuery && !sourceObservationId ? { goal: searchedQuery } : {}
                                    ).url
                                }
                                data-attr="vision-search-create-scanner"
                            >
                                Create a scanner for this
                            </LemonButton>
                        )}
                        <span className="text-xs text-secondary">or try</span>
                        {suggestions
                            .filter((suggestion) => suggestion !== searchedQuery)
                            .map((suggestion) => (
                                <LemonButton
                                    key={suggestion}
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={() => runQuery(suggestion)}
                                    data-attr="vision-search-example"
                                >
                                    {suggestion}
                                </LemonButton>
                            ))}
                    </div>
                </div>
            )}
            <SearchResults {...logicProps} />
        </div>
    )
}
