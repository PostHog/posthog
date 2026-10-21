import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconGitBranch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import {
    FIX_CI_REQUEST,
    inboxTaskKickoffLogic,
    MERGE_PR_REQUEST,
    ReportDiscussionIntent,
} from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { hasApprovedOpenReportPullRequest } from '../../utils/reportPullRequests'

export function DiscussReportButton({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason, freeTrialDisabledReason } =
        useValues(inboxTaskKickoffLogic)
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const { prChecksFailing, selectedPullRequest } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const prActionsEnabled = useFeatureFlag('INBOX_GET_IT_MERGED')
    const canMerge = prActionsEnabled && hasApprovedOpenReportPullRequest(report)
    const canMakeGreen = prActionsEnabled && prChecksFailing

    const startPrAction = (question: string, intent: ReportDiscussionIntent, pullRequestUrl?: string): void => {
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: discussQuestionProperties({ source: 'suggested', suggestionCount: 1, intent }),
        })
        discussReport(report, reportUrl, question, undefined, intent, pullRequestUrl)
    }

    const items: LemonMenuItems = [
        canMerge && {
            label: 'Get it merged',
            icon: <IconGitBranch />,
            tooltip: 'Fix CI on the approved PR and merge it',
            onClick: () => startPrAction(MERGE_PR_REQUEST, 'merge_pr'),
            disabledReason: freeTrialDisabledReason,
            'data-attr': 'inbox-report-ask-ai-merge-pr',
        },
        canMakeGreen && {
            label: 'Make it green',
            icon: <IconCheckCircle />,
            tooltip: 'Fix failing CI on the PR and stop, so you can review and merge it',
            onClick: () => startPrAction(FIX_CI_REQUEST, 'fix_ci', selectedPullRequest.url),
            disabledReason: freeTrialDisabledReason,
            'data-attr': 'inbox-report-ask-ai-fix-ci',
        },
    ]

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles />}
            loading={isDiscussing}
            disabledReason={aiConsentDisabledReason ?? (isCreatingPr ? 'An implementation is starting.' : undefined)}
            onClick={() => openReportDiscussion(report, reportUrl)}
            tooltip="Ask PostHog AI about this report in the sidebar"
            sideAction={
                canMerge || canMakeGreen
                    ? {
                          tooltip: 'More AI actions',
                          'aria-label': 'More AI actions',
                          'data-attr': 'inbox-report-ask-ai-actions',
                          dropdown: {
                              placement: 'bottom-end',
                              overlay: <LemonMenuOverlay items={items} />,
                          },
                      }
                    : undefined
            }
        >
            Ask AI
        </LemonButton>
    )
}
