import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPullRequest, IconX } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { INBOX_SUMMARY_DISMISS_MS, InboxSummaryLogicProps, inboxSummaryLogic } from '../../logics/inboxSummaryLogic'
import { InboxSummaryPeoplePopover } from './InboxSummaryPeoplePopover'
import { InboxSummaryPullRequestsPopover } from './InboxSummaryPullRequestsPopover'

function ProjectSummary(props: InboxSummaryLogicProps): JSX.Element | null {
    const logic = inboxSummaryLogic(props)
    const { summary, summaryLoading, failed, dismissed, pageVisible, hasBeenViewed } = useValues(logic)
    const { dismissSummary, refreshSummary, summaryViewed } = useActions(logic)
    const showSummary = props.visible && pageVisible && !dismissed && !failed && !!summary?.merged_pr_count

    useEffect(() => {
        if (showSummary && !hasBeenViewed) {
            summaryViewed()
        }
    }, [showSummary, hasBeenViewed, summaryViewed])

    if (!props.visible || dismissed) {
        return null
    }
    if (failed) {
        return (
            <div className="mx-6 my-2 flex items-center gap-2 text-secondary text-xs" role="status">
                Summary is not available.
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => refreshSummary(true)}
                    loading={summaryLoading}
                >
                    Try again
                </LemonButton>
            </div>
        )
    }
    if (!summary?.merged_pr_count) {
        return null
    }

    return (
        <LemonCard
            hoverEffect={false}
            className="mx-6 my-3 flex flex-wrap items-center gap-3 p-3 shadow-none"
            data-attr="inbox-value-summary"
        >
            <section aria-label="Self-driving summary" className="contents">
                <IconPullRequest className="shrink-0 text-lg text-success" />
                <div className="min-w-0 flex-1">
                    <h2 className="m-0 text-sm font-semibold">Self-driving activity</h2>
                    <p className="m-0 text-xs text-secondary">
                        <InboxSummaryPullRequestsPopover pullRequests={summary.pull_requests} /> merged with{' '}
                        {summary.participation_complete && summary.people !== null ? (
                            <InboxSummaryPeoplePopover people={summary.people} />
                        ) : (
                            <span className="font-medium text-secondary">people count updating</span>
                        )}{' '}
                        participating in the last 7 days
                    </p>
                </div>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconX />}
                    aria-label="Hide summary for 7 days"
                    tooltip="Hide for 7 days"
                    onClick={() => dismissSummary(Date.now() + INBOX_SUMMARY_DISMISS_MS)}
                />
            </section>
        </LemonCard>
    )
}

export function InboxValueSummary({ visible }: { visible: boolean }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    if (!featureFlags[FEATURE_FLAGS.SIGNALS_INBOX_VALUE_SUMMARY] || !currentTeamId || !user) {
        return null
    }
    return <ProjectSummary teamId={currentTeamId} userId={user.id} visible={visible} />
}
