import { useActions, useValues } from 'kea'

import { IconGitBranch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenuOverlay } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic, MERGE_PR_REQUEST } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'
import { hasApprovedOpenReportPullRequest } from '../../utils/reportPullRequests'

export function DiscussReportButton({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const canMerge = useFeatureFlag('INBOX_GET_IT_MERGED') && hasApprovedOpenReportPullRequest(report)

    const getItMerged = (): void => {
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: discussQuestionProperties({ source: 'suggested', suggestionCount: 1, intent: 'merge_pr' }),
        })
        discussReport(report, reportUrl, MERGE_PR_REQUEST, undefined, 'merge_pr')
    }

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
                canMerge
                    ? {
                          tooltip: 'More AI actions',
                          'aria-label': 'More AI actions',
                          'data-attr': 'inbox-report-ask-ai-actions',
                          dropdown: {
                              placement: 'bottom-end',
                              overlay: (
                                  <LemonMenuOverlay
                                      items={[
                                          {
                                              label: 'Get it merged',
                                              icon: <IconGitBranch />,
                                              tooltip: 'Fix CI on the approved PR and merge it',
                                              onClick: getItMerged,
                                              'data-attr': 'inbox-report-ask-ai-merge-pr',
                                          },
                                      ]}
                                  />
                              ),
                          },
                      }
                    : undefined
            }
        >
            Ask AI
        </LemonButton>
    )
}
