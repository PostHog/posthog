import { Link } from '@posthog/lemon-ui'

import { derivePrState } from 'lib/signals/prState'
import { PrBadge } from 'lib/signals/SignalReportPrBadge'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { ReportPlanApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportStatus } from '../../types'
import { displayConventionalCommitTitle, parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'

export function ReportPlanBlock({ reportId, plan }: { reportId: string; plan: ReportPlanApi }): JSX.Element {
    const stepNumbers = new Map(plan.steps.map((step, index) => [step.id, index + 1]))
    const stepNumber = stepNumbers.get(reportId)
    const planTitle = displayConventionalCommitTitle(plan.title, 'Untitled plan')

    return (
        <section className="flex flex-col gap-2" data-attr="inbox-report-plan">
            <h2 className="m-0 text-lg font-semibold">Plan</h2>
            {plan.id === reportId ? (
                <p className="m-0 text-sm text-secondary">
                    {`Split into ${plan.steps.length} steps. Each step is its own report.`}
                </p>
            ) : (
                <p className="m-0 text-sm text-secondary">
                    <span>{stepNumber ? `Step ${stepNumber} of ${plan.steps.length} in ` : 'A step in '}</span>
                    <Link to={urls.inboxReport('reports', plan.id)} data-attr="inbox-report-plan-open">
                        {planTitle}
                    </Link>
                </p>
            )}
            <ol className="m-0 flex list-none flex-col divide-y divide-primary rounded border border-primary p-0">
                {plan.steps.map((step, index) => {
                    const isCurrent = step.id === reportId
                    const title = displayConventionalCommitTitle(step.title, 'Untitled report')
                    const prUrl = safeHttpUrl(step.implementation_pr_url)
                    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : null
                    const buildsOn = step.depends_on.flatMap((id) => stepNumbers.get(id) ?? [])
                    return (
                        <li
                            key={step.id}
                            aria-current={isCurrent ? 'step' : undefined}
                            className={cn(
                                'flex items-start gap-2 px-3 py-2 text-sm',
                                isCurrent && 'bg-fill-highlight-100'
                            )}
                        >
                            <span className="w-5 shrink-0 text-tertiary tabular-nums">{`${index + 1}.`}</span>
                            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                                {isCurrent ? (
                                    <span className="min-w-0 break-words font-semibold">{title}</span>
                                ) : (
                                    <Link
                                        to={urls.inboxReport('reports', step.id)}
                                        className="min-w-0 break-words"
                                        data-attr="inbox-report-plan-step-open"
                                    >
                                        {title}
                                    </Link>
                                )}
                                <SignalReportStatusBadge status={step.status as SignalReportStatus} />
                                {prNumber ? (
                                    <PrBadge
                                        prNumber={prNumber}
                                        prUrl={prUrl}
                                        state={derivePrState(step.status, false, step.implementation_pr_state)}
                                    />
                                ) : null}
                                {buildsOn.length > 0 ? (
                                    <span className="text-xs text-tertiary">{`Builds on ${buildsOn.join(', ')}`}</span>
                                ) : null}
                            </div>
                        </li>
                    )
                })}
            </ol>
        </section>
    )
}
