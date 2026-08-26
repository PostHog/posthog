import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { IconArrowLeft, IconEllipsis, IconExternal, IconSearch } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { ScoutLink } from 'lib/signals/ScoutLink'
import { scoutDisplayName } from 'lib/signals/signalCardSourceLine'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport, SignalReportStatus, SignalSourceProduct } from '../../types'
import {
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
    parsePrUrlParts,
    safeHttpUrl,
} from '../../utils/reportPresentation'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportBillingBadge } from '../badges/SignalReportBillingBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { isStatusRedundantWithActionability, SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import {
    hasKnownSourceProduct,
    knownSourceProductEntries,
    SourceProductIconRow,
    sourceProductsTooltipTitle,
} from '../badges/sourceProductIcons'
import { ConventionalCommitScopeTag } from '../cards/ReportCard'
import { DetailSection } from './DetailSection'
import { DiscussReportButton } from './DiscussReportButton'
import { PrChecksSection } from './PrChecksSection'
import { PrCommentsSection } from './PrCommentsSection'
import { ReportActivitySection } from './ReportActivitySection'
import { ReportChart } from './ReportChart'
import { useReportDetailActions } from './ReportDetailActions'
import { ReportFeedbackFooter } from './ReportFeedbackFooter'
import { ReportSummaryBody } from './ReportSummaryBody'
import { ReportTasksSection } from './ReportTasksSection'
import { SuggestedReviewersSection } from './SuggestedReviewersSection'

/**
 * Status / priority / actionability badges for a report's detail header. Mirrors desktop `InboxDetailFrame`.
 * The judgment rationale (when present) is sourced from the detail logic's loaded artefacts and surfaced by
 * a circled help icon overlaying the chip's top-right corner; the chip is then hoverable for the rationale.
 */
export function ReportDetailBadges({
    report,
    priorityExplanation,
    actionabilityExplanation,
}: {
    report: SignalReport
    priorityExplanation?: string | null
    actionabilityExplanation?: string | null
}): JSX.Element {
    return (
        <>
            <SignalReportPriorityBadge priority={report.priority} explanation={priorityExplanation} />
            {!isStatusRedundantWithActionability(report.status, report.actionability) && (
                <SignalReportStatusBadge status={report.status} />
            )}
            <SignalReportActionabilityBadge
                actionability={report.actionability}
                explanation={actionabilityExplanation}
            />
            <SignalReportBillingBadge report={report} />
        </>
    )
}

/** Shared explainer for the signal count in the meta line and the Evidence section. */
const SIGNALS_TOOLTIP =
    'Signals are the individual pieces of evidence from your connected sources and scouts that were grouped into this report.'

/**
 * Dot-separated stats under the title (signal count · first seen · last updated · source stack).
 * `evidenceCount` switches to the live signal count once findings load, so the row reads the same
 * before and after the query resolves.
 */
function ReportDetailStats({
    report,
    evidenceCount,
    scoutSkillName,
}: {
    report: SignalReport
    evidenceCount: number
    /** Authoring scout's raw skill slug, when scout-authored — its name links to the scout off the "Scout" chip. */
    scoutSkillName?: string | null
}): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)

    const stats: ReactNode[] = []
    if (evidenceCount > 0) {
        stats.push(
            <Tooltip title={SIGNALS_TOOLTIP}>
                <span className="tabular-nums cursor-help">
                    {evidenceCount} signal{evidenceCount === 1 ? '' : 's'}
                </span>
            </Tooltip>
        )
    }
    // Mirrors error tracking's "First seen" / "Last seen": surface both lifecycle moments as distinct facts.
    stats.push(
        <span className="flex items-center gap-1">
            <span>First seen</span>
            <TZLabel time={report.created_at} />
        </span>
    )
    stats.push(
        <span className="flex items-center gap-1">
            <span>Last updated</span>
            <TZLabel time={report.updated_at ?? report.created_at} />
        </span>
    )
    if (hasSource) {
        stats.push(<MetaSourceStack sourceProducts={report.source_products} scoutSkillName={scoutSkillName} />)
    }

    return (
        <div className="flex items-center gap-2 flex-wrap min-w-0 text-xs text-tertiary leading-none select-none">
            {stats.map((node, i) => (
                <span key={i} className="flex items-center gap-2 min-w-0">
                    {i > 0 && <span aria-hidden>·</span>}
                    {node}
                </span>
            ))}
        </div>
    )
}

/** Source-product icon stack reused inside the detail meta row. */
function MetaSourceStack({
    sourceProducts,
    scoutSkillName,
}: {
    sourceProducts?: string[] | null
    scoutSkillName?: string | null
}): JSX.Element | null {
    const entries = knownSourceProductEntries(sourceProducts)
    const [primary, ...overflow] = entries
    if (!primary) {
        return null
    }
    // Name the authoring scout on a scout-authored report so it's clear at a glance who wrote it,
    // and link the name straight to the scout's detail page. The scout may not sort first among mixed
    // sources, so key off whether any source is a scout rather than just the primary.
    const scoutName = scoutDisplayName(scoutSkillName)
    const showScout = entries.some(({ key }) => key === SignalSourceProduct.SignalsScout) && !!scoutName
    return (
        <Tooltip title={sourceProductsTooltipTitle(entries)}>
            <span className="inline-flex items-center gap-1.5 min-w-0 cursor-help">
                <SourceProductIconRow entries={entries} className="inline-flex items-center gap-1 shrink-0" />
                <span>
                    {primary.meta.label}
                    {showScout && scoutSkillName ? (
                        <>
                            {' · '}
                            <ScoutLink skillName={scoutSkillName} className="text-tertiary" />
                        </>
                    ) : null}
                    {overflow.length > 0 ? ` + ${overflow.length}` : null}
                </span>
            </span>
        </Tooltip>
    )
}

/** Placeholder finding rows shown while the signals query is in flight, sized to the known count. */
function EvidenceSkeleton({ count }: { count: number }): JSX.Element {
    const rows = Math.max(1, Math.min(count, 4))
    return (
        <div className="flex flex-col gap-3" aria-hidden>
            {Array.from({ length: rows }).map((_, i) => (
                <div
                    key={i}
                    className="flex flex-col gap-2 rounded border border-primary bg-surface-primary px-3 py-2.5"
                >
                    <div className="h-3 w-1/3 rounded bg-fill-highlight-100 animate-pulse" />
                    <div className="h-2.5 w-4/5 rounded bg-fill-highlight-50 animate-pulse" />
                </div>
            ))}
        </div>
    )
}

/** Column classes shared by the frame and its skeleton, so the two can't drift apart. */
const DETAIL_PAGE_CLASS = '@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 pb-4 text-sm'
const DETAIL_CONTAINER_CLASS =
    'flex flex-col rounded-lg border border-primary bg-surface-primary @5xl:flex-row @5xl:items-start'
// The evidence rail: first in the DOM so it leads on wide layouts, ordered after the summary when
// the columns stack, because reading the summary first is what a narrow screen wants.
const DETAIL_ASIDE_CLASS =
    'order-2 flex w-full min-w-0 flex-col gap-5 border-t border-primary p-5 @5xl:order-none @5xl:w-[26rem] @5xl:shrink-0 @5xl:self-stretch @5xl:border-t-0 @5xl:border-r'
const DETAIL_MAIN_CLASS = 'order-1 flex min-w-0 flex-1 flex-col px-6 py-5 @5xl:order-none @5xl:px-8'

/**
 * Layout-faithful placeholder shown while a report's base record loads on a cold open (deep link
 * with no list row to seed from). Mirrors `InboxDetailFrame`'s header row + evidence-first
 * two-column container so the page doesn't jump when the real content lands — and so loading
 * reads as "this view, populating" rather than a bare centered spinner.
 */
export function ReportDetailSkeleton(): JSX.Element {
    return (
        <div className={DETAIL_PAGE_CLASS} aria-hidden>
            <div className="flex items-center justify-between gap-3 mb-4">
                <div className="h-8 w-24 rounded bg-fill-highlight-50 animate-pulse" />
                <div className="flex items-center gap-2">
                    <div className="h-8 w-24 rounded bg-fill-highlight-50 animate-pulse" />
                    <div className="h-8 w-20 rounded bg-fill-highlight-50 animate-pulse" />
                </div>
            </div>
            <div className={DETAIL_CONTAINER_CLASS}>
                <div className={DETAIL_ASIDE_CLASS}>
                    {Array.from({ length: 2 }).map((_, i) => (
                        <div key={i} className="flex flex-col gap-2.5">
                            <div className="h-4 w-24 rounded bg-fill-highlight-100 animate-pulse" />
                            <div className="h-16 w-full rounded border border-primary bg-surface-secondary animate-pulse" />
                        </div>
                    ))}
                </div>
                <div className={DETAIL_MAIN_CLASS}>
                    <div className="flex items-center gap-2.5 mb-4 pb-3 border-b border-primary">
                        <div className="h-3.5 w-28 rounded bg-fill-highlight-100 animate-pulse" />
                        <div className="h-4 w-20 rounded bg-fill-highlight-50 animate-pulse" />
                    </div>
                    <div className="flex items-start gap-3 min-w-0">
                        <div className="size-7 shrink-0 mt-0.5 rounded bg-fill-highlight-100 animate-pulse" />
                        <div className="flex flex-col gap-2 min-w-0 flex-1">
                            <div className="h-7 w-2/3 rounded bg-fill-highlight-100 animate-pulse" />
                            <div className="h-3 w-1/2 rounded bg-fill-highlight-50 animate-pulse" />
                        </div>
                    </div>
                    <div className="flex flex-col gap-2.5 mt-6">
                        <div className="h-3 w-full rounded bg-fill-highlight-50 animate-pulse" />
                        <div className="h-3 w-11/12 rounded bg-fill-highlight-50 animate-pulse" />
                        <div className="h-3 w-3/4 rounded bg-fill-highlight-50 animate-pulse" />
                    </div>
                </div>
            </div>
        </div>
    )
}

interface InboxDetailFrameProps {
    report: SignalReport
    /** Content closing the evidence rail, after Activity (e.g. the PR conversation). */
    asideFooter?: ReactNode
    /** Extra primary action(s) rendered after the shared report actions. */
    primaryAction?: ReactNode
    /** Extra sections (Tasks, Reviewers) – defaults applied by callers. */
    children?: ReactNode
}

/**
 * Shared chrome for the Report and Pull request detail bodies. A back link and the actions sit on
 * one row over a bordered container: the evidence rail on the left (Evidence first, then the PR
 * checks, reviewers, runs, and activity), and the report summary on the right under its own
 * "Report summary" header with the title, billing chip, and stats. The status and actionability chips
 * stay off this header: the inbox section the report came from already says what they said.
 * AgentRunDetail keeps its own layout.
 */
export function InboxDetailFrame({ report, asideFooter, primaryAction, children }: InboxDetailFrameProps): JSX.Element {
    const { searchParams } = useValues(router)
    // A `?back=` internal path (set by surfaces embedding inbox cards, e.g. the customer analytics
    // feed) redirects the back button there instead of the inbox list tab.
    const rawBack = searchParams.back
    const backOverride =
        typeof rawBack === 'string' && rawBack.startsWith('/') && !rawBack.startsWith('//') ? rawBack : null
    const backLabel = backOverride ? (backOverride.startsWith(urls.inboxTriage()) ? 'Triage' : 'Back') : 'Inbox'
    const logicProps = { reportId: report.id, report }
    const { reportSignals, reportSignalsLoading, priorityExplanation, chartPlacements, trailingCharts } = useValues(
        inboxReportDetailLogic(logicProps)
    )
    const signals = reportSignals ?? []
    const evidenceCount = reportSignals !== null ? signals.length : report.signal_count
    const hasEvidence = evidenceCount > 0

    const summaryPending =
        report.status === SignalReportStatus.IN_PROGRESS || report.status === SignalReportStatus.CANDIDATE

    // Reading depth on the report body: which supporting sections a reader actually opened.
    const captureSectionToggle = (section: string) => (collapsed: boolean) =>
        captureInboxReportAction({
            report,
            actionType: collapsed ? 'collapse_section' : 'expand_section',
            surface: 'detail_pane',
            extra: { section },
        })

    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const displayTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    // Absolute URL to this report – seeded into the Discuss prompt so the agent can open and read
    // the report directly.
    const reportUrl = `${window.location.origin}${addProjectIdIfMissing(urls.inboxReport('reports', report.id))}`

    // Create PR is the report's main call to action, so it takes the primary slot (styled like
    // "Open in GitHub" on PR-bearing reports). The rest render inline as buttons on wide layouts
    // and as a standard `LemonMenu` on narrow ones.
    const allReportActions = useReportDetailActions(report)
    const createPrAction = allReportActions.find((action) => action.key === 'create-pr')
    const reportActions = allReportActions.filter((action) => action.key !== 'create-pr')
    const overflowMenuItems: LemonMenuItem[] = reportActions.map((action) => ({
        label: action.label,
        icon: action.icon,
        disabledReason: action.loading ? 'Working…' : action.disabledReason,
        onClick: action.onClick,
    }))

    // Bound rather than passed as props so a chart can reach the logic by id alone. `ReportChart`
    // building the logic itself would have to pass `report` back in, and kea treats that as a props
    // change on the mounted instance.
    const overviewBody = (
        <BindLogic logic={inboxReportDetailLogic} props={logicProps}>
            <div className={DETAIL_CONTAINER_CLASS}>
                <aside className={DETAIL_ASIDE_CLASS}>
                    {/* Evidence leads: it is what the summary's claims rest on. */}
                    {hasEvidence && (
                        <DetailSection
                            icon={<IconSearch />}
                            title="Evidence"
                            collapsible
                            onToggleCollapsed={captureSectionToggle('evidence')}
                            rightSlot={
                                <Tooltip title={SIGNALS_TOOLTIP}>
                                    <span className="text-[0.6875rem] text-tertiary tabular-nums cursor-help">
                                        {evidenceCount} signal{evidenceCount === 1 ? '' : 's'}
                                    </span>
                                </Tooltip>
                            }
                        >
                            {reportSignalsLoading && reportSignals === null ? (
                                <EvidenceSkeleton count={evidenceCount} />
                            ) : (
                                <div className="flex flex-col gap-3">
                                    {signals.map((signal: SignalNode) => (
                                        <SignalCard key={signal.signal_id} signal={signal} />
                                    ))}
                                </div>
                            )}
                        </DetailSection>
                    )}
                    {/* Pull request checks (when present), then reviewers, runs, and activity. */}
                    {children}
                    <SuggestedReviewersSection report={report} />
                    <ReportTasksSection report={report} />
                    <ReportActivitySection report={report} />
                    {asideFooter}
                </aside>

                <main className={DETAIL_MAIN_CLASS}>
                    <div className="mb-4 flex flex-wrap items-center gap-2.5 border-b border-primary pb-3">
                        <span className="text-sm font-semibold">Report summary</span>
                        <SignalReportBillingBadge report={report} />
                        <span className="flex-1" />
                        <span className="flex items-center gap-1 text-xs text-tertiary">
                            Generated <TZLabel time={report.created_at} />
                        </span>
                    </div>

                    <div className="flex flex-1 flex-col gap-6">
                        <header className="flex items-start gap-3 min-w-0">
                            {/* Priority square anchors the title. */}
                            {report.priority && (
                                <div className="shrink-0 mt-1">
                                    <SignalReportPriorityBadge
                                        priority={report.priority}
                                        explanation={priorityExplanation}
                                    />
                                </div>
                            )}
                            <div className="flex flex-col gap-2 min-w-0">
                                <h1 className="min-w-0 m-0 break-words text-2xl font-bold leading-tight tracking-tight">
                                    {conventionalTitle && (
                                        <ConventionalCommitScopeTag
                                            type={conventionalTitle.type}
                                            scope={conventionalTitle.scope}
                                        />
                                    )}
                                    {displayTitle}
                                </h1>
                                <ReportDetailStats
                                    report={report}
                                    evidenceCount={evidenceCount}
                                    scoutSkillName={report.scout_name}
                                />
                            </div>
                        </header>

                        <div>
                            {report.summary ? (
                                <ReportSummaryBody
                                    summary={report.summary}
                                    chartPlacements={chartPlacements}
                                    createPrAction={createPrAction}
                                />
                            ) : (
                                <p className={`text-sm text-tertiary m-0${summaryPending ? ' italic' : ''}`}>
                                    No summary yet. An agent is still investigating.
                                </p>
                            )}
                            {trailingCharts.length > 0 && (
                                <div className="flex flex-col gap-4 mt-5">
                                    {trailingCharts.map((chart) => (
                                        <ReportChart key={chart.chart_id} chartId={chart.chart_id} />
                                    ))}
                                </div>
                            )}
                        </div>
                        {/* The rating closes out the report body, pinned to the bottom of the column. */}
                        <div className="mt-auto">
                            <ReportFeedbackFooter report={report} align="end" />
                        </div>
                    </div>
                </main>
            </div>
        </BindLogic>
    )

    return (
        <div className={DETAIL_PAGE_CLASS}>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={backOverride ?? urls.inbox('reports')}
                    className="-ml-4 w-fit"
                    data-attr="inbox-report-back"
                >
                    {backLabel}
                </LemonButton>
                <div className="flex items-center gap-2">
                    {primaryAction}
                    {createPrAction && (
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={createPrAction.icon}
                            loading={createPrAction.loading}
                            tooltip={createPrAction.disabledReason ? undefined : createPrAction.tooltip}
                            disabledReason={createPrAction.disabledReason}
                            onClick={createPrAction.onClick}
                        >
                            {createPrAction.label}
                        </LemonButton>
                    )}
                    {/* Discuss is always available and stays inline as its own dropdown button. */}
                    <DiscussReportButton report={report} reportUrl={reportUrl} />
                    {/* Buttons inline on wide layouts; collapse into a standard LemonMenu kebab below @4xl. */}
                    <div className="hidden @4xl:flex items-center gap-2">
                        {reportActions.map((action) => (
                            <LemonButton
                                key={action.key}
                                type="secondary"
                                size="small"
                                icon={action.icon}
                                loading={action.loading}
                                // A disabled action explains only why it's unavailable — not what it would do.
                                tooltip={action.disabledReason ? undefined : action.tooltip}
                                disabledReason={action.disabledReason}
                                onClick={action.onClick}
                            >
                                {action.label}
                            </LemonButton>
                        ))}
                    </div>
                    {/* A resolved report past its refund window has no secondary actions at all. */}
                    {overflowMenuItems.length > 0 && (
                        <LemonMenu items={overflowMenuItems} placement="bottom-end">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconEllipsis />}
                                aria-label="More actions"
                                className="@4xl:hidden"
                            />
                        </LemonMenu>
                    )}
                </div>
            </div>

            {overviewBody}
        </div>
    )
}

/** Point a PR URL at its diff/files tab, without double-appending if it's already there. */
function prFilesUrl(prUrl: string): string {
    return prUrl.replace(/\/+$/, '').replace(/(\/files)?$/, '/files')
}

/**
 * Unified report detail for Pull requests / Reports / Not actionable. The "Open in GitHub" action
 * surfaces only when the report has a shipped implementation PR; otherwise it reads as a plain
 * report. Runs keep their own `AgentRunDetail`.
 */
export function ReportDetail({ report }: { report: SignalReport }): JSX.Element {
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prRef = prUrl ? parsePrUrlParts(prUrl) : null
    const hasPr = !!(prRef && prUrl)

    return (
        <InboxDetailFrame
            report={report}
            primaryAction={
                hasPr ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        sideIcon={<IconExternal />}
                        to={prFilesUrl(prUrl)}
                        targetBlank
                        tooltip={`${prRef.repoSlug}#${prRef.number}`}
                        onClick={() =>
                            captureInboxReportAction({ report, actionType: 'open_pr', surface: 'detail_pane' })
                        }
                    >
                        Open in GitHub
                    </LemonButton>
                ) : undefined
            }
            // The PR conversation closes the evidence rail, under Activity; CI checks sit higher in
            // the same rail. Both drop themselves when there's nothing to show.
            asideFooter={hasPr ? <PrCommentsSection report={report} /> : undefined}
        >
            {hasPr && <PrChecksSection report={report} />}
        </InboxDetailFrame>
    )
}
