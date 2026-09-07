import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown, IconRefresh, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'
import { ScoutSuggestionCreateHost } from './ScoutSuggestionCreateHost'

/** Titles named on the collapsed line before it gives up and counts the rest. */
const COLLAPSED_TITLE_PREVIEW = 2

/**
 * The "Suggested for this project" strip above the roster: a pre-computed batch of scouts worth
 * running here, each ready to turn on or create without waiting for a scan.
 *
 * Nothing renders until a batch exists, so a project that has never been scanned sees the roster
 * exactly as it was. `stale` is a footer note rather than an error: any fleet change flips it and
 * the picks stay valid.
 *
 * The strip opens collapsed and can be closed outright. A closed strip comes back through the
 * "Suggest a scout" header button, so the picks are never more than one click away.
 */
export function ScoutSuggestionsStrip(): JSX.Element | null {
    const { suggestions, hasBatch, collapsed, stripHidden, isRefreshing, suggestionSet } =
        useValues(scoutSuggestionsLogic)
    const { setCollapsed, hideStrip, requestRefresh } = useActions(scoutSuggestionsLogic)
    useReportSuggestionsShown('strip')

    if (!hasBatch || stripHidden) {
        return null
    }

    const generatedAt = suggestionSet?.generated_at

    return (
        <section className="flex flex-col gap-3 rounded border border-primary bg-surface-secondary p-3">
            <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <div className="flex items-center gap-1.5">
                        <IconSparkles className="text-secondary" />
                        <h3 className="m-0 text-sm font-semibold">Suggested for this project</h3>
                        {suggestions.length > 0 && (
                            <span className="text-xs tabular-nums text-muted">{suggestions.length}</span>
                        )}
                    </div>
                    <span className="text-xs text-muted">
                        Picked by scanning this project's data against the scouts you already run.
                        {generatedAt ? ` Refreshed ${dayjs(generatedAt).fromNow()}.` : ''}
                    </span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={isRefreshing}
                        disabledReason={isRefreshing ? 'Scanning the project…' : undefined}
                        onClick={() => requestRefresh()}
                        data-attr="scout-suggestions-refresh"
                    >
                        Refresh
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                        onClick={() => setCollapsed(!collapsed)}
                        aria-label={collapsed ? 'Show suggested scouts' : 'Hide suggested scouts'}
                        data-attr="scout-suggestions-collapse"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        tooltip="Close. Bring the suggestions back with the Suggest a scout button."
                        onClick={() => hideStrip()}
                        aria-label="Close suggested scouts"
                        data-attr="scout-suggestions-hide"
                    />
                </div>
            </div>

            <StripBody />
            <ScoutSuggestionCreateHost surface="strip" />
        </section>
    )
}

/** Whichever of the strip's four states applies: collapsed, scanning, nothing left, or the cards. */
function StripBody(): JSX.Element {
    const { suggestions, collapsed, batchStatus, isRefreshing, suggestionSetLoading } = useValues(scoutSuggestionsLogic)

    if (collapsed) {
        return <CollapsedLine titles={suggestions.map((item) => item.title)} />
    }
    if (isRefreshing || (suggestionSetLoading && suggestions.length === 0)) {
        return <SuggestionsSkeleton />
    }
    if (suggestions.length === 0) {
        return (
            <p className="m-0 text-xs text-secondary">
                {batchStatus === 'failed'
                    ? "The last scan didn't finish, so there are no picks yet. Refresh to try again, or "
                    : 'Nothing left to suggest right now. Refresh to scan the project again, or '}
                <SuggestWithAiLink />.
            </p>
        )
    }
    return (
        <>
            <SuggestionGrid surface="strip" />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                {batchStatus === 'stale' && (
                    <span>
                        Your scouts changed since these were picked, or the picks are due a refresh, so some may already
                        be covered.
                    </span>
                )}
                {batchStatus === 'failed' && (
                    <span>The last scan didn't finish, so these are the picks from before it.</span>
                )}
                <span>
                    Want something else? <SuggestWithAiLink />.
                </span>
            </div>
        </>
    )
}

/** The suggestion cards on their own, for the empty state's body. */
export function ScoutSuggestionsEmptyStateCards(): JSX.Element | null {
    const { suggestions, hasBatch } = useValues(scoutSuggestionsLogic)
    useReportSuggestionsShown('empty_state')

    if (!hasBatch || suggestions.length === 0) {
        return null
    }

    return (
        <div className="flex w-full flex-col gap-3">
            <SuggestionGrid surface="empty_state" columns={2} />
            <ScoutSuggestionCreateHost surface="empty_state" />
        </div>
    )
}

function SuggestionGrid({ surface, columns = 3 }: { surface: ScoutSuggestionSurface; columns?: 2 | 3 }): JSX.Element {
    const { suggestions } = useValues(scoutSuggestionsLogic)
    return (
        <div
            className={cn(
                'grid grid-cols-1 gap-2',
                // One card in a three-across grid stretches to a third of the row and reads as a
                // gap where the other two should be, so a lone card keeps a single narrow column.
                suggestions.length === 1 ? 'max-w-md' : ['@2xl:grid-cols-2', columns === 3 && '@3xl:grid-cols-3']
            )}
        >
            {suggestions.map((item) => (
                <ScoutSuggestionCard key={item.id} item={item} surface={surface} />
            ))}
        </div>
    )
}

function CollapsedLine({ titles }: { titles: string[] }): JSX.Element {
    if (titles.length === 0) {
        return <span className="text-xs text-muted">Nothing left to suggest right now.</span>
    }
    const named = titles.slice(0, COLLAPSED_TITLE_PREVIEW).join(', ')
    const rest = titles.length - COLLAPSED_TITLE_PREVIEW
    return (
        <span className="truncate text-xs text-secondary">
            {named}
            {rest > 0 ? ` and ${rest} more` : ''}
        </span>
    )
}

function SuggestionsSkeleton(): JSX.Element {
    return (
        <div className="grid grid-cols-1 gap-2 @2xl:grid-cols-2 @3xl:grid-cols-3">
            {[0, 1, 2].map((index) => (
                <div key={index} className="flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3">
                    <LemonSkeleton className="h-3.5 w-16" />
                    <LemonSkeleton className="h-3.5 w-4/5" />
                    <LemonSkeleton className="h-3 w-full" />
                    <LemonSkeleton className="h-6 w-24 rounded" />
                </div>
            ))}
        </div>
    )
}

function SuggestWithAiLink(): JSX.Element {
    const { aiConsentDisabledReason, runningChatType } = useValues(scoutSuggestionsLogic)
    const { startScoutChatTask } = useActions(scoutSuggestionsLogic)
    // The chat ends in a skill write, so it carries the same editor gate as the other authoring paths.
    const creationDisabledReason = useScoutCreateDisabledReason()
    if (creationDisabledReason) {
        return <span>suggest a scout with AI once you can edit skills</span>
    }
    if (aiConsentDisabledReason) {
        return <span>suggest a scout with AI once AI data processing is on</span>
    }
    return (
        <Link
            // The request only shows on screen once it navigates, so without this a second click
            // lands in the gap and mints a second cloud task.
            disabledReason={runningChatType !== null ? 'Starting a task…' : undefined}
            onClick={() => startScoutChatTask('author_scout', 'scout authoring task')}
        >
            suggest a scout with AI
        </Link>
    )
}

/** Fires the impression once per mount, the first time a batch has actually resolved on screen. */
function useReportSuggestionsShown(surface: ScoutSuggestionSurface): void {
    const { hasBatch, stripHidden } = useValues(scoutSuggestionsLogic)
    const { reportSuggestionsShown } = useActions(scoutSuggestionsLogic)
    const reportedRef = useRef(false)
    // The empty state has no close control, so only the strip can be hidden.
    const onScreen = hasBatch && (surface !== 'strip' || !stripHidden)
    useEffect(() => {
        if (!onScreen || reportedRef.current) {
            return
        }
        reportedRef.current = true
        reportSuggestionsShown(surface)
    }, [onScreen, surface, reportSuggestionsShown])
}
