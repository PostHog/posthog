import { type ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { ReportPriorityApi } from 'products/signals/frontend/generated/api.schemas'

import { PRIORITY_MEANING, PRIORITY_TAG_TYPE } from '../../filterOptions'
import { SignalReport } from '../../types'
import { reportClaimant } from '../../utils/reportClaim'
import type { ReportDecisionAttribution, ReportDecisionAttributions } from '../../utils/reportDecisions'
import { safeHttpUrl } from '../../utils/reportPresentation'
import { reportPullRequests } from '../../utils/reportPullRequests'
import { STATUS_LABELS } from '../badges/SignalReportStatusBadge'
import { DetailSection } from './DetailSection'
import { ReportAgentDecisions } from './ReportAgentDecisions'
import { ReportDecisionRow } from './ReportDecisionRow'
import { ReportPullRequestLine } from './ReportPullRequestLine'
import { ReportRepositoryDecisionRow } from './ReportRepositoryDecisionRow'

const PRIORITY_OPTIONS: LemonSelectOptionLeaf<ReportPriorityApi>[] = Object.entries(PRIORITY_MEANING).map(
    ([priority, { label }]) => ({
        value: priority as ReportPriorityApi,
        label: `${priority} · ${label}`,
        labelInMenu: (
            <span className="flex items-center gap-2">
                <LemonTag type={PRIORITY_TAG_TYPE[priority as ReportPriorityApi]} size="small">
                    {priority}
                </LemonTag>
                <span className="text-default">{label}</span>
            </span>
        ),
    })
)

function StatusRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-6 items-center justify-between gap-3">
            <dt className="text-xs text-secondary">{label}</dt>
            <dd className="m-0 flex min-w-0 flex-wrap items-center justify-end gap-1.5 text-right text-xs">
                {children}
            </dd>
        </div>
    )
}

function externalClaimLabel(report: SignalReport): string | null {
    const assignee = report.assignee
    if (assignee?.kind !== 'agent') {
        return null
    }
    const agent = assignee.agent?.trim() || 'External agent'
    const claimant = reportClaimant(report)
    return claimant ? `${fullNameOrEmail(claimant)} (via ${agent})` : agent
}

function PriorityRow({
    priority,
    editable,
    attribution,
    onChange,
    saving,
}: {
    priority: ReportPriorityApi
    editable: boolean
    attribution: ReportDecisionAttribution | null
    onChange?: (priority: ReportPriorityApi) => void
    saving: boolean
}): JSX.Element {
    if (editable) {
        return (
            <ReportDecisionRow<ReportPriorityApi>
                label="Priority"
                value={priority}
                attribution={attribution}
                options={PRIORITY_OPTIONS}
                onChange={onChange}
                saving={saving}
                data-attr="report-priority-select"
            />
        )
    }
    return (
        <StatusRow label="Priority">
            {onChange ? (
                <LemonSelect<ReportPriorityApi>
                    aria-label="Change report priority"
                    data-attr="report-priority-select"
                    value={priority}
                    onChange={onChange}
                    loading={saving}
                    disabledReason={saving ? 'Saving priority…' : undefined}
                    size="xsmall"
                    type="tertiary"
                    dropdownPlacement="bottom-end"
                    dropdownMatchSelectWidth={false}
                    menu={{ className: 'w-56' }}
                    options={PRIORITY_OPTIONS}
                    renderButtonContent={() => <span className="text-default text-xs font-normal">{priority}</span>}
                />
            ) : (
                priority
            )}
        </StatusRow>
    )
}

export function ReportStatusSection({
    report,
    rightSlot,
    onPriorityChange,
    prioritySaving = false,
    onRepositoryChange,
    repositorySaving = false,
    decisionAttributions = null,
    selectedPullRequestUrl = null,
    onSelectPullRequest,
    onToggleAgentDecisions,
}: {
    report: SignalReport
    rightSlot?: ReactNode
    onPriorityChange?: (priority: ReportPriorityApi) => void
    prioritySaving?: boolean
    onRepositoryChange?: (repository: string) => void
    repositorySaving?: boolean
    /** Null before the report's detail loads. */
    decisionAttributions?: ReportDecisionAttributions | null
    selectedPullRequestUrl?: string | null
    onSelectPullRequest?: (url: string) => void
    onToggleAgentDecisions?: (collapsed: boolean) => void
}): JSX.Element {
    const editableDecisions = useFeatureFlag('INBOX_REPORT_EDITABLE_DECISIONS')
    const externalClaim = externalClaimLabel(report)
    const pullRequests = reportPullRequests(report)
    const selectable = pullRequests.length > 1 && !!onSelectPullRequest
    const trackerUrl = safeHttpUrl(report.tracker_issue_url ?? '')

    return (
        <DetailSection icon={<IconInfo />} title="Status" rightSlot={rightSlot} collapsible>
            <div className="flex flex-col gap-2">
                <dl className="m-0 flex flex-col gap-2">
                    <StatusRow label="Report status">{STATUS_LABELS[report.status] ?? report.status}</StatusRow>
                    {externalClaim && <StatusRow label="In progress by">{externalClaim}</StatusRow>}
                    {report.priority && (
                        <PriorityRow
                            priority={report.priority}
                            editable={editableDecisions}
                            attribution={decisionAttributions?.priority ?? null}
                            onChange={onPriorityChange}
                            saving={prioritySaving}
                        />
                    )}
                    {pullRequests.length > 0 && (
                        <div className="flex flex-col gap-1">
                            <dt className="text-xs text-secondary">Pull requests</dt>
                            <dd className="m-0 text-xs">
                                <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                                    {pullRequests.map((pullRequest) => (
                                        <ReportPullRequestLine
                                            key={pullRequest.id ?? pullRequest.url}
                                            pullRequest={pullRequest}
                                            reportRepository={report.repo_slug}
                                            selected={selectable && pullRequest.url === selectedPullRequestUrl}
                                            onSelect={
                                                selectable ? () => onSelectPullRequest(pullRequest.url) : undefined
                                            }
                                        />
                                    ))}
                                </ul>
                            </dd>
                        </div>
                    )}
                    {trackerUrl && (
                        <StatusRow label="Tracker issue">
                            <Link to={trackerUrl} target="_blank">
                                {report.tracker_issue_reference || 'Open issue'}
                            </Link>
                        </StatusRow>
                    )}
                </dl>
                {editableDecisions &&
                    report.repo_slug && (
                        // A wrong repository matters most before a pull request exists, so the group starts open then.
                        <ReportAgentDecisions
                            values={[report.repo_slug]}
                            defaultExpanded={pullRequests.length === 0}
                            onToggleCollapsed={onToggleAgentDecisions}
                        >
                            <ReportRepositoryDecisionRow
                                repository={report.repo_slug}
                                attribution={decisionAttributions?.repository ?? null}
                                onChange={onRepositoryChange}
                                saving={repositorySaving}
                            />
                        </ReportAgentDecisions>
                    )}
            </div>
        </DetailSection>
    )
}
