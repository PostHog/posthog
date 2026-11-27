import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconChevronDown, IconEllipsis, IconRefresh, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, Link, Popover, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { captureScoutSuggestionDisclosureOpened, type ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'
import { ScoutSuggestionCreateHost } from './ScoutSuggestionCreateHost'

/** Titles named on the collapsed bar before it gives up and counts the rest. */
const COLLAPSED_TITLE_PREVIEW = 2

/**
 * The "Suggested scouts" strip above the roster: a pre-computed batch of scouts worth running here,
 * each ready to turn on or create without waiting for a scan.
 *
 * Nothing renders without picks to read, so a project with an empty batch sees the roster exactly
 * as it was. `stale` is a footer note rather than an error: any fleet change flips it and the picks
 * stay valid.
 *
 * The strip opens collapsed and can be closed outright. A closed strip comes back through the
 * "Suggest a scout" header button, so the picks are never more than one click away.
 */
export function ScoutSuggestionsStrip(): JSX.Element | null {
    const { stripVisible, collapsed } = useValues(scoutSuggestionsLogic)
    useReportSuggestionsShown('strip')

    if (!stripVisible) {
        return null
    }

    return (
        <section className="flex flex-col gap-3 rounded border border-primary bg-surface-secondary p-3">
            {collapsed ? <CollapsedHeader /> : <ExpandedHeader />}
            <StripBody />
            <ScoutSuggestionCreateHost surface="strip" />
        </section>
    )
}

/** One bar that names the picks. The bar and its labeled button both expand it. */
function CollapsedHeader(): JSX.Element {
    const { suggestions } = useValues(scoutSuggestionsLogic)
    const { setCollapsed, hideStrip } = useActions(scoutSuggestionsLogic)
    const count = suggestions.length
    const titles = suggestions.map((item) => item.title)
    const rest = titles.length - COLLAPSED_TITLE_PREVIEW

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <button
                type="button"
                onClick={() => setCollapsed(false)}
                className="flex min-w-0 flex-1 basis-60 cursor-pointer flex-col items-start gap-0.5 text-left"
            >
                <span className="flex items-center gap-1.5 text-sm font-semibold">
                    <IconSparkles className="shrink-0 text-secondary" />
                    {count > 0
                        ? `${count} ${count === 1 ? 'scout' : 'scouts'} suggested for this project`
                        : 'Suggested scouts'}
                </span>
                {count > 0 && (
                    <span className="max-w-full truncate text-xs text-secondary">
                        {titles.slice(0, COLLAPSED_TITLE_PREVIEW).join(', ')}
                        {rest > 0 ? ` and ${rest} more` : ''}
                    </span>
                )}
            </button>
            <div className="flex shrink-0 items-center gap-1">
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => setCollapsed(false)}
                    data-attr="scout-suggestions-collapse"
                >
                    Show suggestions
                </LemonButton>
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
    )
}

function ExpandedHeader(): JSX.Element {
    const { suggestions } = useValues(scoutSuggestionsLogic)
    return (
        <div className="flex items-start gap-3">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <IconSparkles className="text-secondary" />
                    <h3 className="m-0 text-sm font-semibold">Suggested scouts</h3>
                    {suggestions.length > 0 && (
                        <span className="text-xs tabular-nums text-muted">{suggestions.length}</span>
                    )}
                    <WhatIsAScoutLink />
                </div>
                <span className="text-xs text-muted">
                    Based on what this project tracks. Nothing runs until you turn it on.
                </span>
            </div>
            <StripMenu />
        </div>
    )
}

function StripMenu(): JSX.Element {
    const { isRefreshing, suggestionSet, runningChatType, aiConsentDisabledReason, scoutChatDisabledReason } =
        useValues(scoutSuggestionsLogic)
    const { requestRefresh, startScoutChatTask, setCollapsed } = useActions(scoutSuggestionsLogic)
    // The chat ends in a skill write, so it carries the same editor gate as the other authoring paths.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const generatedAt = suggestionSet?.generated_at

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    label: (
                        <span className="flex flex-col items-start">
                            <span>Refresh suggestions</span>
                            {generatedAt && (
                                <span className="text-xs text-muted">
                                    Refreshed <TZLabel time={generatedAt} showPopover={false} />
                                </span>
                            )}
                        </span>
                    ),
                    icon: <IconRefresh />,
                    disabledReason: isRefreshing ? 'Scanning the project…' : undefined,
                    onClick: () => requestRefresh('strip'),
                    'data-attr': 'scout-suggestions-refresh',
                },
                {
                    label: 'Suggest a scout with AI',
                    icon: <IconSparkles />,
                    // The request only shows on screen once it navigates, so without this a second
                    // click lands in the gap and mints a second cloud task.
                    disabledReason:
                        runningChatType !== null
                            ? 'Starting a task…'
                            : (creationDisabledReason ??
                              aiConsentDisabledReason ??
                              scoutChatDisabledReason ??
                              undefined),
                    onClick: () => startScoutChatTask('author_scout', 'scout authoring task'),
                    'data-attr': 'scout-suggestions-author-with-ai',
                },
                {
                    label: 'Hide suggestions',
                    icon: <IconChevronDown />,
                    onClick: () => setCollapsed(true),
                    'data-attr': 'scout-suggestions-collapse',
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                aria-label="Suggested scouts options"
                data-attr="scout-suggestions-menu"
            />
        </LemonMenu>
    )
}

/** Opens on press rather than hover, so a phone can read it too. */
function WhatIsAScoutLink(): JSX.Element {
    const [open, setOpen] = useState(false)
    const toggle = (): void => {
        if (!open) {
            captureScoutSuggestionDisclosureOpened({ disclosure: 'whats_a_scout', surface: 'strip' })
        }
        setOpen(!open)
    }
    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-start"
            overlay={
                <div className="flex max-w-80 flex-col gap-2 p-1 text-sm">
                    <p className="m-0">A scout is an agent that checks one part of your project on a schedule.</p>
                    <p className="m-0">
                        When it finds something worth your attention, it files a report in your inbox. You choose what
                        each scout watches and how often it runs.
                    </p>
                </div>
            }
        >
            <Link className="text-xs" onClick={toggle} aria-expanded={open} data-attr="scout-suggestions-whats-a-scout">
                What's a scout?
            </Link>
        </Popover>
    )
}

/** Whichever of the strip's states applies: collapsed, placeholders with nothing yet to read, or the rows. */
function StripBody(): JSX.Element | null {
    const { suggestions, collapsed, batchStatus, isRefreshing, suggestionSetLoading } = useValues(scoutSuggestionsLogic)

    if (collapsed) {
        // Without titles the strip is only up because a scan is running, so the note is all there is to show.
        return isRefreshing ? <ScanningNote /> : null
    }
    if (suggestions.length === 0 && (isRefreshing || suggestionSetLoading)) {
        return (
            <>
                <SuggestionsSkeleton />
                {isRefreshing && <ScanningNote />}
            </>
        )
    }
    return (
        <>
            <SuggestionList surface="strip" />
            {isRefreshing && <ScanningNote />}
            {batchStatus === 'stale' && (
                <span className="text-xs text-muted">
                    Your scouts changed since these were picked, or the picks are due a refresh, so some may already be
                    covered.
                </span>
            )}
            {batchStatus === 'failed' && (
                <span className="text-xs text-muted">
                    The last scan didn't finish, so these are the picks from before it.
                </span>
            )}
            {batchStatus === 'low_activity' && (
                <span className="text-xs text-muted">
                    This project has been quiet, so the last scan was skipped and these are the picks from before it.
                </span>
            )}
        </>
    )
}

/** The suggestion rows on their own, for the empty state's body. */
export function ScoutSuggestionsEmptyStateCards(): JSX.Element | null {
    const { hasPicks } = useValues(scoutSuggestionsLogic)
    useReportSuggestionsShown('empty_state')

    if (!hasPicks) {
        return null
    }

    return (
        <div className="flex w-full flex-col gap-3">
            <SuggestionList surface="empty_state" />
            <ScoutSuggestionCreateHost surface="empty_state" />
        </div>
    )
}

/** Full-width rows with dividers, the same shape as the roster rows under the strip. */
function SuggestionList({ surface }: { surface: ScoutSuggestionSurface }): JSX.Element {
    const { suggestions } = useValues(scoutSuggestionsLogic)
    return (
        <div className="@container divide-y divide-primary overflow-hidden rounded border border-primary bg-surface-primary">
            {suggestions.map((item) => (
                <ScoutSuggestionCard key={item.id} item={item} surface={surface} />
            ))}
        </div>
    )
}

/** The picks a scan will replace are still on screen, so without this line a press looks ignored. */
function ScanningNote(): JSX.Element {
    const { refreshElapsedLabel } = useValues(scoutSuggestionsLogic)
    return (
        <div className="flex items-start gap-1.5 text-xs text-muted">
            <Spinner className="mt-0.5 shrink-0" />
            <span>
                Scanning the project for new picks{refreshElapsedLabel ? `: ${refreshElapsedLabel}` : ''}. It usually
                takes 2 to 5 minutes. You can leave this page. The new picks will be here when you come back.
            </span>
        </div>
    )
}

function SuggestionsSkeleton(): JSX.Element {
    return (
        <div className="divide-y divide-primary rounded border border-primary bg-surface-primary">
            {[0, 1, 2].map((index) => (
                <div key={index} className="flex flex-col gap-1.5 px-3 py-2.5">
                    <LemonSkeleton className="h-3.5 w-1/3" />
                    <LemonSkeleton className="h-3 w-4/5" />
                    <LemonSkeleton className="h-3 w-24" />
                </div>
            ))}
        </div>
    )
}

/** Fires the impression once per mount, the first time picks have actually reached the screen. */
function useReportSuggestionsShown(surface: ScoutSuggestionSurface): void {
    const { hasPicks, stripHidden } = useValues(scoutSuggestionsLogic)
    const { reportSuggestionsShown } = useActions(scoutSuggestionsLogic)
    const reportedRef = useRef(false)
    // The empty state has no close control, so only the strip can be hidden.
    const onScreen = hasPicks && (surface !== 'strip' || !stripHidden)
    useEffect(() => {
        if (!onScreen || reportedRef.current) {
            return
        }
        reportedRef.current = true
        reportSuggestionsShown(surface)
    }, [onScreen, surface, reportSuggestionsShown])
}
