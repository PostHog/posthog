import clsx from 'clsx'
import { router } from 'kea-router'

import { IconHide, IconUndo } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { derivePrState } from 'lib/signals/prState'
import { ScoutLink } from 'lib/signals/ScoutLink'
import { scoutDisplayName } from 'lib/signals/signalCardSourceLine'
import { PrBadge } from 'lib/signals/SignalReportPrBadge'

import {
    INBOX_SECTION_LEGACY_TAB,
    InboxReportSectionKey,
    SignalReport,
    SignalReportStatus,
    SignalSourceProduct,
} from '../../types'
import { dismissalReasonLabel, DismissalFeedback, isResolveReason } from '../../utils/dismissalReasons'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import {
    deriveHeadline,
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
    knownSourceProductEntries,
    SourceProductIconRow,
    sourceProductsTooltipTitle,
} from '../badges/sourceProductIcons'
import { inboxCardRowClassName } from './inboxCardRowClassName'
import { useReportDismiss } from './useReportDismiss'

// ── Shared card sub-components ────────────────────────────────────────────────

export function ConventionalCommitScopeTag({ type, scope }: { type: string; scope: string | null }): JSX.Element {
    const label = scope ? `${type}(${scope})` : type
    // Rendered as an inline prefix to the title text (not a flex sibling), so it stays on the
    // title's first line and the title wraps beneath it. `align-middle` keeps it centered on that
    // line; `font-normal` stops it inheriting the title's weight.
    return (
        <LemonTag size="small" className="mr-1 align-middle font-mono font-normal select-none" title={label}>
            {label}
        </LemonTag>
    )
}

/** Icon stack + primary source-product label, with a `+ n` tail when more sources contributed. */
export function InboxCardSourceMeta({
    sourceProducts,
    scoutSkillName,
}: {
    sourceProducts?: string[] | null
    /** Authoring scout's raw skill slug, when scout-authored — its name links to the scout off the "Scout" label. */
    scoutSkillName?: string | null
}): JSX.Element | null {
    const entries = knownSourceProductEntries(sourceProducts)
    const [primary, ...overflow] = entries
    if (!primary) {
        return null
    }
    // Name the authoring scout on a scout-authored report so it's clear at a glance who wrote it,
    // and link the name straight to the scout's detail page.
    const scoutName = scoutDisplayName(scoutSkillName)
    const showScout = primary.key === SignalSourceProduct.SignalsScout && !!scoutName
    return (
        <Tooltip title={sourceProductsTooltipTitle(entries)}>
            <div className="flex items-center gap-2 min-w-0 text-xs text-tertiary leading-none select-none cursor-help">
                <SourceProductIconRow entries={entries} className="flex items-center gap-1.5 shrink-0" />
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
            </div>
        </Tooltip>
    )
}

// ── PR status badge ─────────────────────────────────────────────────────────

// ── ReportCard ────────────────────────────────────────────────────────────────

/**
 * Unified inbox list card for reports and pull requests. The presence of a parseable
 * implementation PR (`hasPr`) drives the divergences: PR cards get a solid border, a
 * `#1234` state badge, the repo slug in the meta row, no status/actionability chips, and a
 * "Review" action; plain reports get a dashed border, a summary placeholder, and the
 * status/actionability chips.
 *
 * Under the redesign the row itself is the way in: the whole card links to the report detail, so
 * there is no separate open button. Dismissing and resolving live in the report detail pane and the
 * bulk selection bar, where what is being judged is in full view. Other surfaces that embed this
 * card can still opt into a row-level Dismiss via `onDismiss`. The redesign also drops the status
 * and actionability chips: the state a row is in (Needs decision, Not actionable, ...) already says
 * what they said. With the flag off every row keeps its chips, its Dismiss button, and "Review".
 */
export function ReportCard({
    report,
    sectionKey = 'needs-decision',
    attached = false,
    onDismiss,
    onRestore,
    backUrl,
    preview = false,
}: {
    report: SignalReport
    sectionKey?: InboxReportSectionKey
    attached?: boolean
    /** Dismiss from the row. The inbox list omits it; surfaces that embed this card can opt in. */
    onDismiss?: (dismissal: DismissalFeedback) => void
    onRestore?: () => void
    /** Internal path the detail view's back button should return to, for cards rendered outside the inbox. */
    backUrl?: string
    /** Onboarding sample: render as a static card with no detail link and no focusable actions, so its
     * placeholder report id can never be opened (it 404s). */
    preview?: boolean
}): JSX.Element {
    // Keyed on status, not the section: the legacy Archive tab lists dismissed and resolved rows
    // through one section key, and the two need different affordances.
    const isDismissed = report.status === SignalReportStatus.SUPPRESSED
    // Resolved reports are terminal (a merged PR or a resolve) – shown for reference in the Resolved
    // section. They can't be restored or dismissed; refunding their PR lives in the detail pane.
    const isResolved = report.status === SignalReportStatus.RESOLVED
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prUrlParts = prUrl ? parsePrUrlParts(prUrl) : null
    const hasPr = prUrlParts != null
    const prNumber = prUrlParts?.number ?? null
    const repoSlug = prUrlParts?.repoSlug ?? null

    const isReady = report.status === 'ready'
    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const cardTitle = displayConventionalCommitTitle(report.title, hasPr ? 'Untitled pull request' : 'Untitled report')
    const headline = deriveHeadline(report.summary)
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    // The legacy layout addresses a report through the tab that listed it, so its back control returns there.
    const detailUrl = inboxReportDetailUrl(
        report.id,
        backUrl,
        redesign ? 'reports' : INBOX_SECTION_LEGACY_TAB[sectionKey]
    )

    const { isDismissing, onDismissClick } = useReportDismiss({
        reportId: report.id,
        cardTitle,
        report,
        surface: 'list_row',
        onDismiss,
    })

    const isRefunded = !!report.refund
    const showsDismiss = !!onDismiss || !redesign

    // Why the report left the inbox (reason tag + note tooltip) when we have it: the dismiss reason
    // on dismissed rows, and a resolve reason on rows resolved by hand. A report that was dismissed,
    // restored, then resolved by a merged PR keeps its old dismissal artefact, so a resolved row only
    // shows a reason that describes a resolve (see `isResolveReason`). The dedicated billing badge
    // already marks refunded reports, so skip the duplicate chip there.
    const outcomeLabel =
        !isRefunded && (isDismissed || (isResolved && isResolveReason(report.dismissal_reason)))
            ? dismissalReasonLabel(report.dismissal_reason)
            : null

    const cardBodyClassName = 'flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline'
    const cardBody = (
        <>
            {report.priority && (
                <div className="shrink-0">
                    <SignalReportPriorityBadge priority={report.priority} />
                </div>
            )}

            <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                {/* Keep the title clear of the PR badge, which is positioned within the content column. */}
                <div
                    className={clsx(
                        'min-w-0 break-words font-semibold text-sm leading-snug text-balance',
                        hasPr && 'pr-14'
                    )}
                >
                    {conventionalTitle && (
                        <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                    )}
                    {cardTitle}
                </div>

                {headline ? (
                    <p
                        className={clsx(
                            'min-w-0',
                            !hasPr && !isReady && 'opacity-80',
                            'break-words line-clamp-2 text-xs text-secondary leading-snug m-0'
                        )}
                    >
                        {headline}
                    </p>
                ) : !hasPr ? (
                    <p
                        className={clsx(
                            'min-w-0',
                            !isReady && 'opacity-80',
                            'break-words line-clamp-2 text-xs text-tertiary italic leading-snug m-0'
                        )}
                    >
                        No summary yet. Still collecting context.
                    </p>
                ) : null}

                <div className="flex items-center flex-wrap mt-1.5 min-w-0 gap-x-2.5 gap-y-1 text-xs text-tertiary leading-none select-none">
                    {hasPr && repoSlug ? <span className="truncate font-mono">{repoSlug}</span> : null}
                    <InboxCardSourceMeta sourceProducts={report.source_products} scoutSkillName={report.scout_name} />
                    {!hasPr &&
                        !redesign &&
                        !isStatusRedundantWithActionability(report.status, report.actionability) && (
                            <SignalReportStatusBadge status={report.status} />
                        )}
                    {!hasPr && !redesign && report.actionability && (
                        <SignalReportActionabilityBadge actionability={report.actionability} />
                    )}
                    {outcomeLabel && (
                        <Tooltip title={report.dismissal_note || undefined}>
                            <LemonTag
                                size="small"
                                icon={
                                    <span
                                        className={clsx(
                                            'size-1.5 shrink-0 rounded-full',
                                            isResolved ? 'bg-success' : 'bg-danger'
                                        )}
                                    />
                                }
                            >
                                {outcomeLabel}
                            </LemonTag>
                        </Tooltip>
                    )}
                    <SignalReportBillingBadge report={report} />
                    <TZLabel
                        time={report.updated_at ?? report.created_at}
                        className="ml-auto shrink-0 text-xs text-tertiary tabular-nums"
                        title="Last updated"
                    />
                </div>
            </div>
        </>
    )

    return (
        <div
            className={clsx(
                inboxCardRowClassName(attached, { dashed: !hasPr }),
                // Closed rows recede so open work stands out in the mixed flat list; hover restores
                // full opacity for reading. Matches the disabled-scout treatment in ScoutRosterCard.
                (isDismissed || isResolved) && 'opacity-55 hover:opacity-100'
            )}
        >
            <div className="relative flex min-w-0 flex-1">
                {hasPr && prNumber != null ? (
                    <div className="absolute right-0 top-0 z-10">
                        <PrBadge
                            prNumber={prNumber}
                            // No link in preview mode: the sample PR url is fabricated, and a link would
                            // stay keyboard-focusable inside the otherwise non-routable card.
                            prUrl={preview ? null : prUrl}
                            state={derivePrState(report.status, report.implementation_pr_merged === true)}
                        />
                    </div>
                ) : null}

                {preview ? (
                    <div className={cardBodyClassName}>{cardBody}</div>
                ) : (
                    <Link to={detailUrl} className={cardBodyClassName}>
                        {cardBody}
                    </Link>
                )}
            </div>

            {/* Refund deliberately isn't offered at the card level – it lives in the report detail
                pane, where the consequences are in view. Resolved reports are terminal and a refunded
                dismissed report can't be restored, so neither carries actions – skip the column (and
                divider) for both. */}
            {!isResolved && !(isDismissed && isRefunded) && (isDismissed || showsDismiss || !redesign) && (
                <div className="flex items-center justify-end gap-2.5 shrink-0 @lg:self-stretch @lg:border-l @lg:border-primary @lg:pl-3">
                    {isDismissed ? (
                        // A refunded report can't be restored (its PR can never be billed again).
                        !isRefunded && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconUndo />}
                                tooltip="Restore this report to the inbox"
                                aria-label="Restore this report to the inbox"
                                onClick={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    onRestore?.()
                                }}
                            >
                                Restore
                            </LemonButton>
                        )
                    ) : (
                        <>
                            {showsDismiss && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconHide />}
                                    tooltip="Dismiss this report"
                                    aria-label="Dismiss this report"
                                    loading={isDismissing}
                                    onClick={preview ? undefined : onDismissClick}
                                    tabIndex={preview ? -1 : undefined}
                                >
                                    Dismiss
                                </LemonButton>
                            )}
                            {!redesign && (
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    tooltip="Open the full report to see its summary, evidence, and actions"
                                    onClick={
                                        preview
                                            ? undefined
                                            : (event) => {
                                                  event.preventDefault()
                                                  event.stopPropagation()
                                                  router.actions.push(detailUrl)
                                              }
                                    }
                                    tabIndex={preview ? -1 : undefined}
                                >
                                    Review
                                </LemonButton>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    )
}
