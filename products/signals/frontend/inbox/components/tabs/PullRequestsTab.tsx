import { useValues } from 'kea'

import { IconPullRequest } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ReportCard } from '../cards/ReportCard'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { InboxReportList } from '../InboxReportList'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'

export function PullRequestsTab(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showWaitingForWork = featureFlags[FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE] === 'empty-state'

    return (
        <InboxReportList
            tabKey="pulls"
            Card={ReportCard}
            emptyState={
                showWaitingForWork
                    ? { content: <InboxWaitingForWork /> }
                    : {
                          icon: <IconPullRequest className="text-2xl" />,
                          title: 'No pull requests right now',
                          description:
                              'When an agent ships a code change, the PR draft lands here for you to review and publish.',
                          extra: (
                              <SelfDrivingInstallingHint>
                                  Pull requests will be opened as soon as live data comes in.
                              </SelfDrivingInstallingHint>
                          ),
                      }
            }
        />
    )
}
