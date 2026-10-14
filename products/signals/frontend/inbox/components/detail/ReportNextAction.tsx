import { useActions, useValues } from 'kea'

import { IconClock, IconPullRequest, IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import type { SignalReport } from '../../types'
import { reportInvestigationPrompt, reportNextStep } from '../../utils/reportNextStep'
import { ImplementButton } from './ImplementButton'

export function ReportNextAction({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { reportArtefactsLoading, reportTasks, reportTasksLoading, implementationSlotClaim, selectedPullRequest } =
        useValues(logic)
    const { selectPullRequest, setDetailTab, loadReportArtefacts } = useActions(logic)
    const { isCreatingPr, isDiscussing, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { openReportDiscussion, discussReport, openReportTask } = useActions(inboxTaskKickoffLogic)
    const step = reportNextStep(report, reportTasks, implementationSlotClaim, selectedPullRequest.url)

    if (step.kind === 'none') {
        return null
    }
    if (step.kind === 'implement') {
        return <ImplementButton report={report} />
    }
    if (step.kind === 'load') {
        const isLoading = reportArtefactsLoading || reportTasksLoading
        return (
            <LemonButton size="small" loading={isLoading} onClick={loadReportArtefacts} tooltip={step.reason}>
                {isLoading ? 'Checking runs' : 'Reload runs'}
            </LemonButton>
        )
    }
    if (step.kind === 'wait') {
        return <span className="text-xs text-secondary">{step.reason}</span>
    }
    if (step.kind === 'review') {
        return (
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPullRequest />}
                tooltip={step.reason}
                data-attr="inbox-report-review-pr"
                onClick={() => {
                    selectPullRequest(step.url)
                    setDetailTab('files')
                }}
            >
                {step.label}
            </LemonButton>
        )
    }
    if (step.kind === 'task') {
        return (
            <LemonButton
                type="primary"
                size="small"
                icon={<IconClock />}
                tooltip={step.reason}
                data-attr="inbox-report-open-task"
                onClick={() => {
                    captureInboxReportAction({ report, actionType: 'open_task', surface: 'detail_pane' })
                    openReportTask(report, step.taskId, step.runId)
                }}
            >
                View task
            </LemonButton>
        )
    }
    const investigate = (): void => {
        if (isCreatingPr || isDiscussing || aiConsentDisabledReason) {
            return
        }
        const reportUrl = `${window.location.origin}${addProjectIdIfMissing(urls.inboxReport('reports', report.id))}`
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: {
                ...discussQuestionProperties({ source: 'preset', suggestionCount: 0 }),
                next_step: 'investigate',
            },
        })
        openReportDiscussion(report, reportUrl)
        discussReport(
            report,
            reportUrl,
            'Check the evidence and identify the next step.',
            reportInvestigationPrompt(report.id, reportUrl)
        )
    }
    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconSearch />}
            tooltip={step.reason}
            loading={isDiscussing}
            disabledReason={aiConsentDisabledReason ?? (isCreatingPr ? 'An implementation is starting.' : undefined)}
            data-attr="inbox-report-investigate"
            onClick={investigate}
        >
            Investigate
        </LemonButton>
    )
}
