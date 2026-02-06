import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronRight, IconClock, IconEye, IconEyeHidden } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SignalReportApi } from './generated/api.schemas'
import { InboxTab, inboxLogic } from './inboxLogic'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxLogic,
}

function weightToSeverity(weight: number): { label: string; color: 'danger' | 'warning' | 'muted' } {
    if (weight >= 5) {
        return { label: 'Critical', color: 'danger' }
    }
    if (weight >= 2) {
        return { label: 'Important', color: 'warning' }
    }
    return { label: 'Low', color: 'muted' }
}

function ReportListItem({
    report,
    isSelected,
    onSelect,
}: {
    report: SignalReportApi
    isSelected: boolean
    onSelect: () => void
}): JSX.Element {
    const severity = weightToSeverity(report.total_weight)

    return (
        <button
            onClick={onSelect}
            className={`w-full text-left px-4 py-3 border-b border-primary transition-colors cursor-pointer ${
                isSelected
                    ? 'bg-surface-light dark:bg-fill-highlight-100'
                    : 'hover:bg-surface-light dark:hover:bg-fill-highlight-50'
            }`}
        >
            <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <LemonTag type={severity.color} size="small">
                            {severity.label}
                        </LemonTag>
                        {report.signal_count > 1 && (
                            <span className="text-xs text-muted">{report.signal_count} signals</span>
                        )}
                    </div>
                    <h3 className="text-sm font-semibold text-primary truncate mb-0.5">
                        {report.title || 'Untitled report'}
                    </h3>
                    <p className="text-xs text-secondary line-clamp-2 mb-1">
                        {report.summary || 'No summary available'}
                    </p>
                    <div className="flex items-center gap-3 text-xs text-muted">
                        <span className="flex items-center gap-1">
                            <IconClock className="size-3" />
                            {humanFriendlyDetailedTime(report.created_at)}
                        </span>
                        {report.relevant_user_count != null && (
                            <span>
                                {report.relevant_user_count} user{report.relevant_user_count !== 1 ? 's' : ''} affected
                            </span>
                        )}
                    </div>
                </div>
                <IconChevronRight className="size-4 text-muted shrink-0 mt-1" />
            </div>
        </button>
    )
}

function ReportDetail({ report }: { report: SignalReportApi }): JSX.Element {
    const severity = weightToSeverity(report.total_weight)
    const { dismissedReportIds } = useValues(inboxLogic)
    const { dismissReport, undoDismissReport } = useActions(inboxLogic)
    const isDismissed = dismissedReportIds.includes(report.id)

    return (
        <div className="p-6 max-w-3xl">
            <div className="flex items-center gap-3 mb-4">
                <LemonTag type={severity.color}>{severity.label}</LemonTag>
                <span className="text-xs text-muted">Weight: {report.total_weight.toFixed(1)}</span>
            </div>

            <h1 className="text-xl font-bold text-primary mb-2">{report.title || 'Untitled report'}</h1>

            <div className="flex items-center gap-4 text-sm text-secondary mb-6">
                <span className="flex items-center gap-1">
                    <IconClock className="size-3.5" />
                    {humanFriendlyDetailedTime(report.created_at)}
                </span>
                {report.signal_count > 0 && (
                    <span>
                        {report.signal_count} signal{report.signal_count !== 1 ? 's' : ''}
                    </span>
                )}
                {report.relevant_user_count != null && (
                    <span>
                        {report.relevant_user_count} user{report.relevant_user_count !== 1 ? 's' : ''} affected
                    </span>
                )}
                {report.artefact_count > 0 && (
                    <span>
                        {report.artefact_count} artefact{report.artefact_count !== 1 ? 's' : ''}
                    </span>
                )}
            </div>

            <div className="border border-primary rounded-lg p-4 mb-6 bg-surface-primary">
                <h3 className="text-sm font-semibold text-primary mb-2">Summary</h3>
                <p className="text-sm text-secondary leading-relaxed whitespace-pre-wrap">
                    {report.summary || 'No summary available for this report.'}
                </p>
            </div>

            <div className="flex items-center gap-2">
                {isDismissed ? (
                    <LemonButton type="secondary" icon={<IconEye />} onClick={() => undoDismissReport(report.id)}>
                        Move to active
                    </LemonButton>
                ) : (
                    <LemonButton type="secondary" icon={<IconEyeHidden />} onClick={() => dismissReport(report.id)}>
                        Dismiss
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function EmptyState({ tab }: { tab: InboxTab }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center h-full text-center p-8">
            {tab === 'active' ? (
                <>
                    <IconCheck className="size-12 text-success mb-4" />
                    <h2 className="text-lg font-semibold text-primary mb-1">All clear</h2>
                    <p className="text-sm text-secondary max-w-sm">
                        No actionable reports right now. We'll surface new ones as we analyze your product sessions.
                    </p>
                </>
            ) : (
                <>
                    <IconEyeHidden className="size-12 text-muted mb-4" />
                    <h2 className="text-lg font-semibold text-primary mb-1">No dismissed reports</h2>
                    <p className="text-sm text-secondary max-w-sm">
                        Reports you dismiss will appear here so you can revisit them later.
                    </p>
                </>
            )}
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const {
        visibleReports,
        selectedReport,
        selectedReportId,
        activeTab,
        reportsLoading,
        activeReports,
        dismissedReports,
    } = useValues(inboxLogic)
    const { setActiveTab, setSelectedReportId } = useActions(inboxLogic)

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-primary px-4 h-[var(--scene-layout-header-height)]">
                <div className="flex items-center gap-3">
                    <h1 className="text-base font-bold mb-0">Inbox</h1>
                    {activeReports.length > 0 && (
                        <span className="bg-danger text-white text-xs font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                            {activeReports.length}
                        </span>
                    )}
                </div>
            </div>

            <div className="flex flex-1 min-h-0">
                {/* Left panel: report list */}
                <div className="w-[380px] shrink-0 border-r border-primary flex flex-col min-h-0">
                    {/* Tabs */}
                    <div className="flex border-b border-primary">
                        <button
                            onClick={() => setActiveTab('active')}
                            className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors relative ${
                                activeTab === 'active' ? 'text-primary' : 'text-muted hover:text-secondary'
                            }`}
                        >
                            Active
                            {activeReports.length > 0 && (
                                <span className="ml-1.5 text-xs text-muted">({activeReports.length})</span>
                            )}
                            {activeTab === 'active' && (
                                <div className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full" />
                            )}
                        </button>
                        <button
                            onClick={() => setActiveTab('dismissed')}
                            className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors relative ${
                                activeTab === 'dismissed' ? 'text-primary' : 'text-muted hover:text-secondary'
                            }`}
                        >
                            Dismissed
                            {dismissedReports.length > 0 && (
                                <span className="ml-1.5 text-xs text-muted">({dismissedReports.length})</span>
                            )}
                            {activeTab === 'dismissed' && (
                                <div className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full" />
                            )}
                        </button>
                    </div>

                    {/* Report list */}
                    <div className="flex-1 overflow-y-auto">
                        {reportsLoading ? (
                            <div className="flex items-center justify-center h-32">
                                <Spinner className="text-muted" />
                            </div>
                        ) : visibleReports.length === 0 ? (
                            <EmptyState tab={activeTab} />
                        ) : (
                            visibleReports.map((report) => (
                                <ReportListItem
                                    key={report.id}
                                    report={report}
                                    isSelected={report.id === selectedReportId}
                                    onSelect={() => setSelectedReportId(report.id)}
                                />
                            ))
                        )}
                    </div>
                </div>

                {/* Right panel: report detail */}
                <div className="flex-1 overflow-y-auto bg-surface-primary">
                    {selectedReport ? (
                        <ReportDetail report={selectedReport} />
                    ) : (
                        <div className="flex items-center justify-center h-full text-sm text-muted">
                            {reportsLoading ? (
                                <Spinner className="text-muted" />
                            ) : visibleReports.length > 0 ? (
                                'Select a report to view details'
                            ) : (
                                <EmptyState tab={activeTab} />
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

export default InboxScene
