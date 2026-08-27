import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconArchive, IconArrowLeft, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { TZLabel } from 'lib/components/TZLabel'
import { HotkeyInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { captureInboxPanelViewed } from '../../inboxAnalytics'
import { inboxTriageLogic } from '../../logics/inboxTriageLogic'
import { SignalReport } from '../../types'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
} from '../../utils/reportPresentation'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { ConventionalCommitScopeTag, InboxCardSourceMeta } from '../cards/ReportCard'

/**
 * Wrap a hotkey so it stays quiet while a dialog (the archive form) is up. The hotkey listener sits
 * on `window`, and a modal's buttons are not inputs, so without this pressing the archive key on the
 * archive dialog's own button would stack a second dialog.
 */
function outsideDialogs(action: () => void): HotkeyInterface['action'] {
    return (event) => {
        if ((event.target as Element | null)?.closest?.('.LemonModal')) {
            return
        }
        action()
    }
}

export type TriageEnterIntent = 'passthrough' | 'open' | 'toggle'

/**
 * What the Enter chord does in triage, from the focused element and whether a modifier is held.
 * Command/Ctrl+Enter opens the report from anywhere in the view — even when a just-clicked control
 * still holds focus — so the modifier is checked before the plain-button guard. A focused link keeps
 * its own Enter (activate it, or open in a new tab with the modifier), a key inside a dialog belongs
 * to the dialog, and plain Enter on a focused button activates it rather than toggling the card.
 */
export function triageEnterIntent(target: HTMLElement | null, hasModifier: boolean): TriageEnterIntent {
    if (target?.closest('a, .LemonModal')) {
        return 'passthrough'
    }
    if (hasModifier) {
        return 'open'
    }
    if (target?.closest('button')) {
        return 'passthrough'
    }
    return 'toggle'
}

function PeekStrip({
    report,
    shortcut,
    onClick,
    dataAttr,
}: {
    report: SignalReport
    shortcut: JSX.Element
    onClick: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            data-attr={dataAttr}
            className="flex w-full max-w-2xl flex-none items-center gap-3 overflow-hidden rounded border border-primary bg-surface-primary px-4 py-1.5 opacity-50 transition-opacity hover:opacity-100 motion-reduce:transition-none"
        >
            {shortcut}
            <span className="truncate text-xs text-secondary">
                {displayConventionalCommitTitle(report.title, 'Untitled report')}
            </span>
        </button>
    )
}

function HintBarItem({ shortcut, label }: { shortcut: JSX.Element; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1.5">
            {shortcut}
            <span>{label}</span>
        </span>
    )
}

function TriageCard({ report, expanded }: { report: SignalReport; expanded: boolean }): JSX.Element {
    const { canCreatePr, isCreatingPr, aiConsentDisabledReason, currentReportUrl } = useValues(inboxTriageLogic)
    const { archiveCurrent, createPrForCurrent, openCurrent, toggleExpanded } = useActions(inboxTriageLogic)

    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const title = displayConventionalCommitTitle(report.title, 'Untitled report')
    const headline = deriveHeadline(report.summary)

    return (
        <article
            key={report.id}
            className="flex max-h-full w-full max-w-3xl min-h-0 flex-col overflow-hidden rounded-lg border border-primary bg-surface-primary shadow-sm"
            data-attr="inbox-triage-card"
        >
            <div className="flex flex-none items-center px-6 pt-4">
                <InboxCardSourceMeta sourceProducts={report.source_products} scoutSkillName={report.scout_name} />
            </div>

            <div className="flex flex-none items-center gap-3 px-6 pt-3">
                {report.priority && (
                    <div className="shrink-0">
                        <SignalReportPriorityBadge priority={report.priority} />
                    </div>
                )}
                <h1
                    className={cn(
                        'm-0 min-w-0 break-words font-bold leading-tight tracking-tight',
                        expanded ? 'text-base' : 'text-xl'
                    )}
                >
                    {conventionalTitle && (
                        <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                    )}
                    {title}
                </h1>
            </div>

            {!expanded ? (
                <>
                    <p className="m-0 flex-none px-6 pt-3 text-sm leading-relaxed text-secondary">
                        {headline ?? (
                            <span className="italic text-tertiary">No summary yet. Still collecting context.</span>
                        )}
                    </p>
                    <div className="flex flex-none flex-wrap items-center gap-x-2 gap-y-1 px-6 pt-3 pb-4 text-xs text-tertiary">
                        {report.signal_count > 0 && (
                            <>
                                <span className="tabular-nums">
                                    {report.signal_count} signal{report.signal_count === 1 ? '' : 's'}
                                </span>
                                <span aria-hidden>·</span>
                            </>
                        )}
                        <span className="flex items-center gap-1">
                            First seen <TZLabel time={report.created_at} />
                        </span>
                        <span aria-hidden>·</span>
                        <span className="flex items-center gap-1">
                            Last updated <TZLabel time={report.updated_at ?? report.created_at} />
                        </span>
                    </div>
                </>
            ) : (
                <div className="mt-3 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto border-t border-primary px-6 py-5">
                    {report.summary ? (
                        <LemonMarkdown
                            className="text-sm text-secondary leading-relaxed break-words [&>*+*]:mt-3 [&_li]:my-1 [&_ul]:my-2 [&_ol]:my-2 [&_h1]:mt-5 [&_h2]:mt-5 [&_h3]:mt-4"
                            disableImages
                            // Charts need the report page's placement logic; here their references
                            // drop out and the full report link below carries the reader to them.
                            renderChartRef={() => null}
                        >
                            {report.summary}
                        </LemonMarkdown>
                    ) : (
                        <p className="m-0 text-sm italic text-tertiary">
                            No summary yet. An agent is still investigating.
                        </p>
                    )}
                    <div className="flex items-center gap-2">
                        <Link
                            to={currentReportUrl ?? undefined}
                            className="text-xs"
                            data-attr="inbox-triage-full-report"
                        >
                            Full report
                        </Link>
                        <KeyboardShortcut command enter className="text-accent" />
                    </div>
                </div>
            )}

            <div className="flex flex-none flex-wrap items-center gap-2 border-t border-primary px-4 py-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconArchive />}
                    onClick={archiveCurrent}
                    sideIcon={<KeyboardShortcut a />}
                    data-attr="inbox-triage-archive"
                >
                    Archive
                </LemonButton>
                {canCreatePr && (
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPullRequest />}
                        onClick={createPrForCurrent}
                        loading={isCreatingPr}
                        disabledReason={aiConsentDisabledReason ?? undefined}
                        sideIcon={<KeyboardShortcut c />}
                        data-attr="inbox-triage-create-pr"
                    >
                        Create PR
                    </LemonButton>
                )}
                <div className="flex-1" />
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={openCurrent}
                    sideIcon={<KeyboardShortcut o />}
                    data-attr="inbox-triage-open-report"
                >
                    Open report
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={toggleExpanded}
                    sideIcon={<KeyboardShortcut enter />}
                    data-attr="inbox-triage-toggle-summary"
                >
                    {expanded ? 'Collapse' : 'Read summary'}
                </LemonButton>
            </div>
        </article>
    )
}

/**
 * Triage mode, at `/inbox/reports/triage`: the Needs-a-decision queue one report at a time, with the
 * previous and next reports peeking above and below. Every action has a key, and the hint bar at the
 * bottom lists them.
 */
export function InboxTriageView(): JSX.Element {
    const {
        reports,
        isLoaded,
        isRestoringPosition,
        reportsLoadFailed,
        currentReport,
        previousReport,
        nextReport,
        expanded,
        counter,
    } = useValues(inboxTriageLogic)
    const { navigate, toggleExpanded, setExpanded, archiveCurrent, createPrForCurrent, openCurrent, ensureLoaded } =
        useActions(inboxTriageLogic)

    useKeyboardHotkeys(
        {
            j: { action: outsideDialogs(() => navigate(1)) },
            arrowdown: { action: outsideDialogs(() => navigate(1)) },
            k: { action: outsideDialogs(() => navigate(-1)) },
            arrowup: { action: outsideDialogs(() => navigate(-1)) },
            enter: {
                action: (event) => {
                    const intent = triageEnterIntent(event.target as HTMLElement | null, event.metaKey || event.ctrlKey)
                    if (intent === 'passthrough') {
                        return
                    }
                    event.preventDefault()
                    if (intent === 'open') {
                        openCurrent()
                    } else {
                        toggleExpanded()
                    }
                },
                willHandleEvent: true,
            },
            e: { action: outsideDialogs(() => toggleExpanded()) },
            o: { action: outsideDialogs(() => openCurrent()) },
            a: { action: outsideDialogs(() => archiveCurrent()) },
            c: { action: outsideDialogs(() => createPrForCurrent()) },
            escape: {
                // Escape peels back one layer: the expanded summary, then triage mode itself.
                action: outsideDialogs(() => {
                    if (expanded) {
                        setExpanded(false)
                    } else {
                        router.actions.push(urls.inbox('reports'))
                    }
                }),
            },
        },
        [expanded, navigate, toggleExpanded, setExpanded, archiveCurrent, createPrForCurrent, openCurrent]
    )

    // Once per open, when the queue has settled, so the panel shows up next to the other
    // list-replacing surfaces with how much there was to triage.
    const viewedFiredRef = useRef(false)
    useEffect(() => {
        if (isLoaded && !viewedFiredRef.current) {
            viewedFiredRef.current = true
            captureInboxPanelViewed({ panel: 'triage', itemCount: reports.length })
        }
    }, [isLoaded, reports.length])

    return (
        // The card is centered in whatever height the scene gives; the 70vh floor keeps it centered
        // on a page that doesn't stretch its scene (Storybook, an embedded frame) instead of
        // collapsing to the top.
        <div className="-mt-2 flex min-h-[70vh] flex-1 flex-col overflow-hidden">
            <div className="flex items-center justify-between gap-2 px-4">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={urls.inbox('reports')}
                    className="-ml-2"
                    data-attr="inbox-triage-back"
                >
                    Reports
                </LemonButton>
                <Tooltip title="Your place in the reports that need a pull request">
                    <span className="text-xs text-tertiary tabular-nums">{counter}</span>
                </Tooltip>
            </div>

            <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 py-4">
                {!isLoaded && reportsLoadFailed ? (
                    // The first load failed: kea loaders keep the response null, so `isLoaded` never
                    // flips and the skeleton would otherwise spin forever. Offer a retry instead.
                    <div className="flex flex-col items-center gap-2 text-center">
                        <h3 className="m-0 text-base font-semibold">Couldn't load your reports.</h3>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => ensureLoaded()}
                            data-attr="inbox-triage-retry"
                        >
                            Retry
                        </LemonButton>
                    </div>
                ) : !isLoaded || isRestoringPosition ? (
                    <div className="flex w-full max-w-3xl flex-col gap-3" aria-hidden>
                        <LemonSkeleton className="h-8 w-full max-w-2xl self-center rounded" />
                        <LemonSkeleton className="h-48 w-full rounded-lg" />
                        <LemonSkeleton className="h-8 w-full max-w-2xl self-center rounded" />
                    </div>
                ) : !currentReport ? (
                    <div className="flex flex-col items-center gap-2 text-center">
                        <h3 className="m-0 text-base font-semibold">Inbox zero. Nice.</h3>
                        <p className="m-0 text-sm text-tertiary">
                            Nothing needs a decision right now. The hedgehogs are still out sniffing for more.
                        </p>
                        <LemonButton type="secondary" size="small" to={urls.inbox('reports')}>
                            Back to reports
                        </LemonButton>
                    </div>
                ) : (
                    <>
                        {previousReport && (
                            <PeekStrip
                                report={previousReport}
                                shortcut={<KeyboardShortcut arrowup />}
                                onClick={() => navigate(-1)}
                                dataAttr="inbox-triage-peek-previous"
                            />
                        )}
                        <TriageCard report={currentReport} expanded={expanded} />
                        {nextReport && (
                            <PeekStrip
                                report={nextReport}
                                shortcut={<KeyboardShortcut arrowdown />}
                                onClick={() => navigate(1)}
                                dataAttr="inbox-triage-peek-next"
                            />
                        )}
                    </>
                )}
            </main>

            <footer className="flex flex-none flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-primary px-4 py-1.5 text-xxs text-tertiary">
                <HintBarItem shortcut={<KeyboardShortcut arrowdown />} label="next" />
                <HintBarItem shortcut={<KeyboardShortcut arrowup />} label="previous" />
                <HintBarItem shortcut={<KeyboardShortcut command enter />} label="open report" />
                <HintBarItem shortcut={<KeyboardShortcut escape />} label="back" />
            </footer>
        </div>
    )
}
