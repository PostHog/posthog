import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonCard, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { INBOX_SUMMARY_DISMISS_MS, InboxSummaryLogicProps, inboxSummaryLogic } from '../../logics/inboxSummaryLogic'

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
        <LemonCard hoverEffect={false} className="mx-6 my-3 p-4" data-attr="inbox-value-summary">
            <section aria-label="Self-driving summary" className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <h2 className="m-0 text-sm font-semibold">Self-driving in the last 7 days</h2>
                    <p className="m-0 mt-1 text-xs text-secondary">Entire project</p>
                    <dl className="mb-0 mt-3 flex flex-wrap gap-x-8 gap-y-3">
                        <div>
                            <dt className="text-xs text-secondary">PRs merged</dt>
                            <dd className="m-0 text-2xl font-semibold tabular-nums">
                                {summary.merged_pr_count.toLocaleString()}
                            </dd>
                        </div>
                        <div>
                            <Tooltip title="Distinct people who approved or merged these PRs. Bots are excluded.">
                                <dt className="text-xs text-secondary">People who approved or merged</dt>
                            </Tooltip>
                            <dd className="m-0 text-2xl font-semibold tabular-nums">
                                {summary.participation_complete && summary.people_count !== null ? (
                                    summary.people_count.toLocaleString()
                                ) : (
                                    <span className="text-sm font-normal text-secondary">People count is updating</span>
                                )}
                            </dd>
                        </div>
                    </dl>
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
