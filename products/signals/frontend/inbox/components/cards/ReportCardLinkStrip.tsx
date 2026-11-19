import clsx from 'clsx'

import { IconClock, IconCopy, IconRefresh, IconStack, IconUndo } from '@posthog/icons'
import { LemonButton, LemonMenu, Link, Tooltip } from '@posthog/lemon-ui'

import { derivePrState } from 'lib/signals/prState'
import { PrBadge } from 'lib/signals/SignalReportPrBadge'

import type {
    LinkedReportRefApi,
    LinkPlanSummaryApi,
    LinkStripKindEnumApi,
    PlanStepStateEnumApi,
    ReportLinkKindEnumApi,
    ReportLinkSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

import { captureInboxReportLinkStripClicked } from '../../inboxAnalytics'
import { SignalReport, SignalReportStatus } from '../../types'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { STATUS_LABELS } from '../badges/SignalReportStatusBadge'

const MAX_NUMBERED_STEPS = 5

const KIND_LABEL: Record<ReportLinkKindEnumApi, string> = {
    part_of: 'Part of',
    recurrence_of: 'Came back after',
    duplicate_of: 'Duplicate of',
    depends_on: 'Waiting on',
    follow_up_of: 'Follow-up of',
}

const KIND_ICON: Record<LinkStripKindEnumApi, typeof IconStack> = {
    part_of: IconStack,
    plan: IconStack,
    recurrence_of: IconRefresh,
    duplicate_of: IconCopy,
    depends_on: IconClock,
    follow_up_of: IconUndo,
}

const STEP_STATE_LABEL: Record<PlanStepStateEnumApi, string> = {
    merged: 'Merged',
    in_review: 'In review',
    waiting: 'Waiting',
    dismissed: 'Dismissed',
}

const STEP_DOT_CLASS: Record<PlanStepStateEnumApi, string> = {
    merged: 'bg-[var(--color-purple-600)] dark:bg-[var(--color-purple-400)]',
    in_review: 'bg-success',
    waiting: 'border border-secondary',
    dismissed: 'bg-danger opacity-60',
}

function LinkedReportState({ report }: { report: LinkedReportRefApi }): JSX.Element {
    const prUrl = safeHttpUrl(report.implementation_pr_url ?? '')
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : null
    if (prUrl && prNumber) {
        return (
            <PrBadge
                prNumber={prNumber}
                prUrl={prUrl}
                state={derivePrState(report.status, false, report.implementation_pr_state)}
            />
        )
    }
    return (
        <span className="whitespace-nowrap text-tertiary">
            {STATUS_LABELS[report.status as SignalReportStatus] ?? report.status}
        </span>
    )
}

function stepLabel(step: LinkPlanSummaryApi['steps'][number]): string {
    return `${step.title ?? 'Untitled layer'} · ${STEP_STATE_LABEL[step.state]}`
}

function PlanSteps({
    plan,
    currentId,
    onOpenStep,
}: {
    plan: LinkPlanSummaryApi
    currentId: string
    onOpenStep: (stepId: string, position: number) => void
}): JSX.Element {
    if (plan.steps.length > MAX_NUMBERED_STEPS) {
        const merged = plan.steps.filter((step) => step.state === 'merged').length
        return (
            <span className="flex items-center gap-2">
                <LemonMenu
                    items={plan.steps.map((step, index) => ({
                        label: `${index + 1}. ${stepLabel(step)}`,
                        to: inboxReportDetailUrl(step.id),
                        active: step.id === currentId,
                        onClick: () => onOpenStep(step.id, index + 1),
                    }))}
                >
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        aria-label="Show every layer of this plan"
                        data-attr="report-card-link-strip-layers"
                    >
                        <span className="flex items-center gap-0.5">
                            {plan.steps.map((step) => (
                                <span
                                    key={step.id}
                                    className={clsx(
                                        'size-2 rounded-xs',
                                        STEP_DOT_CLASS[step.state],
                                        step.id === currentId && 'ring-1 ring-accent ring-offset-1'
                                    )}
                                />
                            ))}
                        </span>
                    </LemonButton>
                </LemonMenu>
                <span className="whitespace-nowrap text-tertiary tabular-nums">{merged} merged</span>
            </span>
        )
    }
    return (
        <span className="flex items-center">
            {plan.steps.map((step, index) => (
                <span key={step.id} className="flex items-center">
                    {index > 0 && <span className="h-px w-1.5 bg-[var(--color-border-primary)]" />}
                    <Tooltip title={stepLabel(step)}>
                        <Link
                            to={inboxReportDetailUrl(step.id)}
                            onClick={() => onOpenStep(step.id, index + 1)}
                            aria-label={`Layer ${index + 1}: ${stepLabel(step)}`}
                            data-attr="report-card-link-strip-step"
                            className={clsx(
                                'flex h-5 items-center gap-1 rounded border px-1.5 tabular-nums no-underline',
                                step.id === currentId
                                    ? 'border-accent font-semibold text-primary'
                                    : 'border-primary text-secondary hover:border-secondary hover:text-primary'
                            )}
                        >
                            <span className={clsx('size-1.5 shrink-0 rounded-full', STEP_DOT_CLASS[step.state])} />
                            {index + 1}
                        </Link>
                    </Tooltip>
                </span>
            ))}
        </span>
    )
}

/**
 * The strip across the bottom of an inbox row: the one link to another report that matters most for
 * it. A plan layer shows its plan and a button per layer; any further links sit behind "+N more".
 */
export function ReportCardLinkStrip({
    report,
    summary,
}: {
    report: SignalReport
    summary: ReportLinkSummaryApi
}): JSX.Element {
    const Icon = KIND_ICON[summary.kind]
    const plan = summary.plan
    const isRecurrence = summary.kind === 'recurrence_of'

    let label: string
    let target: { id: string; title: string | null } | null = summary.report
    if (summary.kind === 'plan' && plan) {
        label = `Plan with ${plan.steps.length} layers`
        target = null
    } else if (summary.kind === 'part_of' && plan) {
        label = plan.position ? `Layer ${plan.position} of ${plan.steps.length} in` : 'Part of'
        target = plan
    } else {
        label = KIND_LABEL[summary.kind as ReportLinkKindEnumApi]
    }

    const capture = (
        params: Omit<Parameters<typeof captureInboxReportLinkStripClicked>[0], 'report' | 'summary'>
    ): void => captureInboxReportLinkStripClicked({ report, summary, ...params })

    return (
        <div
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-primary bg-surface-secondary px-4 py-1.5 text-xs @lg:flex-nowrap"
            data-attr="report-card-link-strip"
        >
            <span className="flex min-w-0 basis-full items-center gap-1.5 @lg:flex-1 @lg:basis-auto">
                <Icon className={clsx('size-4 shrink-0', isRecurrence ? 'text-warning' : 'text-secondary')} />
                <span className={clsx('shrink-0 font-semibold', isRecurrence && 'text-warning')}>{label}</span>
                {target && (
                    <Link
                        to={inboxReportDetailUrl(target.id)}
                        onClick={() => capture({ target: 'linked_report', linkedReportId: target.id })}
                        className="min-w-0 truncate"
                        data-attr="report-card-link-strip-report"
                    >
                        {target.title ?? 'Untitled report'}
                    </Link>
                )}
            </span>
            <span className="flex shrink-0 items-center gap-2 @lg:ml-auto">
                {plan && (summary.kind === 'part_of' || summary.kind === 'plan') ? (
                    <PlanSteps
                        plan={plan}
                        currentId={report.id}
                        onOpenStep={(stepId, position) =>
                            capture({ target: 'plan_step', linkedReportId: stepId, stepPosition: position })
                        }
                    />
                ) : summary.report ? (
                    <LinkedReportState report={summary.report} />
                ) : null}
                {summary.other_links.length > 0 && (
                    <LemonMenu
                        items={summary.other_links.map((link) => ({
                            label: `${KIND_LABEL[link.kind]} ${link.report.title ?? 'Untitled report'}`,
                            to: inboxReportDetailUrl(link.report.id),
                            onClick: () =>
                                capture({
                                    target: 'other_link',
                                    linkedReportId: link.report.id,
                                    linkedKind: link.kind,
                                }),
                        }))}
                    >
                        <LemonButton size="xsmall" type="tertiary" data-attr="report-card-link-strip-more">
                            +{summary.other_links.length} more
                        </LemonButton>
                    </LemonMenu>
                )}
            </span>
        </div>
    )
}
