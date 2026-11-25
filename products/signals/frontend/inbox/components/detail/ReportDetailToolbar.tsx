import { ReactNode } from 'react'

import { IconArrowLeft, IconEllipsis, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import { INBOX_SCENE_NAME } from '../../inboxSceneLogic'
import { SignalReport } from '../../types'
import { ReportPullRequestRef } from '../../utils/reportPresentation'
import { DiscussReportButton } from './DiscussReportButton'
import { OpenPullRequestButton } from './OpenPullRequestButton'
import { ReportDetailAction } from './ReportDetailActions'

export interface ReportDetailToolbarProps {
    report: SignalReport
    reportUrl: string
    pullRequest?: ReportPullRequestRef
    /** Where back goes when a `?back=` link opened the report, instead of the inbox. */
    backOverride?: { name: string; path: string }
    /** Implement, which `ReportDetail` builds because it reads that page's logics. */
    implementAction: ReactNode
    reportActions: ReportDetailAction[]
    evidenceRailCollapsed: boolean
    onToggleEvidenceRail: () => void
}

export function ReportDetailToolbar({
    report,
    reportUrl,
    pullRequest,
    implementAction,
    reportActions,
    evidenceRailCollapsed,
    onToggleEvidenceRail,
    backOverride,
}: ReportDetailToolbarProps): JSX.Element {
    const back = backOverride ?? { name: INBOX_SCENE_NAME, path: urls.inbox('reports') }
    return (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div className="-ml-4 flex items-center gap-1">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={back.path}
                    className="w-fit"
                    data-attr="inbox-report-back"
                >
                    {back.name}
                </LemonButton>
                {/* Hiding the rail gives the report column the full width, which is what reading a diff needs. The
                    toggle keeps its place in both states, so it never jumps. */}
                {evidenceRailCollapsed ? (
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconSidebarOpen />}
                        tooltip="Show evidence"
                        aria-label="Show evidence"
                        onClick={onToggleEvidenceRail}
                        data-attr="inbox-report-show-evidence-rail"
                    />
                ) : (
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconSidebarClose />}
                        tooltip="Hide evidence to widen the report"
                        aria-label="Hide evidence"
                        onClick={onToggleEvidenceRail}
                        data-attr="inbox-report-hide-evidence-rail"
                    />
                )}
            </div>
            <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                {pullRequest && <OpenPullRequestButton report={report} pullRequest={pullRequest} />}
                {implementAction}
                <DiscussReportButton report={report} reportUrl={reportUrl} />
                <div className="hidden @4xl:flex items-center gap-2">
                    {reportActions.map((action) => (
                        <LemonButton
                            key={action.key}
                            type={action.primary ? 'primary' : 'secondary'}
                            size="small"
                            icon={action.icon}
                            loading={action.loading}
                            // A disabled action explains only why it's unavailable, not what it would do.
                            tooltip={action.disabledReason ? undefined : action.tooltip}
                            disabledReason={action.disabledReason}
                            onClick={action.onClick}
                        >
                            {action.label}
                        </LemonButton>
                    ))}
                </div>
                {/* A resolved report past its refund window has no secondary actions at all. */}
                {reportActions.length > 0 && (
                    <LemonMenu
                        items={reportActions.map((action) => ({
                            label: action.label,
                            icon: action.icon,
                            disabledReason: action.loading ? 'Working…' : action.disabledReason,
                            onClick: action.onClick,
                        }))}
                        placement="bottom-end"
                    >
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
    )
}
