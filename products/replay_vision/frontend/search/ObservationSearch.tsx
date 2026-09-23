import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import * as researchPng from '@posthog/brand/hoggies/png/research'
import { IconChevronDown, IconClock, IconPlusSmall, IconSearch, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, Popover, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { visionScannersListLogic } from '../logics/visionScannersListLogic'
import { type ReplayScanner, scannerFromApi } from '../replay_scanners/types'
import { type ObservationSearchLogicProps, observationSearchLogic } from './observationSearchLogic'
import { SearchResults } from './SearchResults'

const HedgehogResearch = pngHoggie(researchPng)

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

    const selectedApi = scanners.find((scanner) => scanner.id === scannerId)
    const selectedScanner = selectedApi ? scannerFromApi(selectedApi) : null
    const suggestions = suggestedQueries.length > 0 ? suggestedQueries : exampleQueries(selectedScanner)
    const typed = query.trim().toLowerCase()
    const matchingRecents = recentQueries.filter((recent) => recent !== query && recent.toLowerCase().includes(typed))
    const consentReason = dataProcessingAccepted ? undefined : 'AI data processing is turned off for your organization'
    const idle = results === null && !searching
    const submitDisabledReason =
        consentReason ?? (searching ? 'Searching' : !query.trim() ? 'Describe what to look for first' : undefined)
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
        } else if (event.key === 'Enter' && !submitDisabledReason) {
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
    const scopeItems = [
        { label: 'All scanners', active: scannerId === null, onClick: () => setScannerId(null) },
        ...[...scanners]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((scanner) => ({
                label: scanner.name,
                active: scanner.id === scannerId,
                onClick: () => setScannerId(scanner.id),
            })),
    ]
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
                        <LemonMenu items={scopeItems} placement="bottom-end">
                            <LemonButton
                                size="small"
                                type="secondary"
                                sideIcon={<IconChevronDown />}
                                className="max-w-64"
                                data-attr="vision-search-scope"
                            >
                                <span className="truncate">{selectedScanner?.name ?? 'All scanners'}</span>
                            </LemonButton>
                        </LemonMenu>
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        // The palette popover wraps the input, and buttons inside a popover reference grow a chevron.
                        sideIcon={null}
                        onClick={search}
                        disabledReason={submitDisabledReason}
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
                <div className="flex flex-col items-center gap-3 pt-4">
                    <HedgehogResearch className="w-32 h-32" />
                    <h2 className="text-xl font-semibold m-0">What happened in your sessions?</h2>
                    <span className="text-sm text-secondary">
                        Describe a behavior in plain words. Results are ranked by how well they match.
                    </span>
                </div>
            )}
            {/* One subtree for both states, so the input keeps focus and state when the first results land. */}
            <div className={clsx('flex flex-col items-center gap-2', idle && 'w-full max-w-3xl self-center')}>
                <Popover
                    visible={!idle && paletteOpen && dataProcessingAccepted}
                    onClickOutside={() => setPaletteOpen(false)}
                    placement="bottom-start"
                    matchWidth
                    padded={false}
                    overlay={palette}
                >
                    <div className="w-full max-w-3xl">{input}</div>
                </Popover>
                {idle && <div className="w-full border border-primary rounded-lg bg-surface-primary">{palette}</div>}
            </div>
            {results?.length === 0 && !searching && (
                <div className="rounded bg-surface-secondary px-3 py-6 flex flex-col items-center gap-3 text-center">
                    <HedgehogResearch className="w-24 h-24" />
                    <div className="flex flex-col items-center gap-3 min-w-0 max-w-2xl">
                        <div className="text-sm text-secondary">
                            {scannerId
                                ? `No matches in ${selectedScanner?.name ?? 'this scanner'} for "${searchedQuery}".`
                                : `No matches for "${searchedQuery}". Only sessions a scanner has analyzed are searchable, so nothing found can also mean no scanner is watching for this yet.`}
                        </div>
                        <div className="flex flex-wrap items-center justify-center gap-2">
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
                </div>
            )}
            <SearchResults {...logicProps} />
        </div>
    )
}
