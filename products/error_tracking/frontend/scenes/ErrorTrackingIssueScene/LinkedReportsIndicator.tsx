import { useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonMenu, Link, Tooltip } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { reportFix, reportStatusLabel } from 'lib/signals/SignalReportFixOrStatus'
import { PrBadge } from 'lib/signals/SignalReportPrBadge'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

const TOOLTIP = 'Self-driving is a PostHog agent that investigates errors against your codebase.'

/**
 * The tint the app already uses to mark an AI affordance, as on Max's own controls. In a header row of
 * plain controls it does the work the AI-coloured edge does on the wider report surfaces: this was our
 * software acting, not a teammate.
 */
const AI_CHIP = 'h-5 gap-1 rounded border border-ai bg-ai/08 dark:bg-ai/20 px-1.5 text-xs font-semibold'

function reportTitle(report: SignalReportApi): string {
    return capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))
}

/** The PostHog mark rather than a generic sparkle, so an agent's work is attributable to us at a glance. */
function AgentMark(): JSX.Element {
    return <Logomark variant="mono" color="primary" className="h-3.5 w-auto shrink-0" />
}

/**
 * One report: the state is the whole point, so it sits in the header rather than behind a disclosure.
 *
 * The mark and the state label link to the report, and the pull request badge keeps its own link to
 * GitHub, because an anchor cannot contain another.
 */
function SingleReport({ report }: { report: SignalReportApi }): JSX.Element {
    const fix = reportFix(report)
    return (
        <div className="flex items-center gap-1.5">
            <Tooltip title={`${TOOLTIP} It opened this report for the error.`}>
                <Link
                    to={urls.inboxReport('reports', report.id)}
                    className={cn('flex items-center text-inherit no-underline hover:text-inherit', AI_CHIP)}
                    data-attr="error-tracking-linked-report"
                >
                    <AgentMark />
                    {fix ? fix.label : reportStatusLabel(report)}
                </Link>
            </Tooltip>
            {fix && <PrBadge prNumber={fix.prNumber} prUrl={fix.prUrl} state={fix.state} />}
        </div>
    )
}

/**
 * Several reports: the header states how many, and the titles that distinguish them go in a menu.
 *
 * Each item states its own fix as text rather than a `PrBadge`, because the item is already a link to
 * the report and an anchor cannot contain another.
 */
function SeveralReports({ reports }: { reports: SignalReportApi[] }): JSX.Element {
    return (
        <LemonMenu
            items={reports.map((report) => {
                const fix = reportFix(report)
                return {
                    key: report.id,
                    to: urls.inboxReport('reports', report.id),
                    label: (
                        <div className="flex flex-col gap-0.5 py-0.5">
                            <span className="text-sm font-medium leading-snug">{reportTitle(report)}</span>
                            <span className="text-xs text-muted-alt">
                                {fix ? `${fix.label} (#${fix.prNumber})` : reportStatusLabel(report)}
                            </span>
                        </div>
                    ),
                }
            })}
            placement="bottom-end"
        >
            <ButtonPrimitive
                size="fit"
                className={AI_CHIP}
                tooltip={`${TOOLTIP} It opened ${reports.length} reports for this error.`}
                data-attr="error-tracking-linked-reports"
            >
                <AgentMark />
                {reports.length} reports
                <IconChevronDown className="size-3" />
            </ButtonPrimitive>
        </LemonMenu>
    )
}

/** Renders nothing when the inbox never investigated this issue, which is the common case. */
export function LinkedReportsIndicatorDisplay({ reports }: { reports: SignalReportApi[] }): JSX.Element | null {
    if (reports.length === 0) {
        return null
    }
    return reports.length === 1 ? <SingleReport report={reports[0]} /> : <SeveralReports reports={reports} />
}

/**
 * What self-driving already did about this error, in the issue header beside its status and assignee.
 *
 * This lives in the header rather than the scene panel because the panel starts closed on every page
 * load and, unlike the description toggle beside it, is not persisted. A fix somebody has to click to
 * find is a fix nobody knows about.
 */
export function LinkedReportsIndicator(): JSX.Element | null {
    const { linkedReports } = useValues(errorTrackingIssueSceneLogic)
    return <LinkedReportsIndicatorDisplay reports={linkedReports} />
}
