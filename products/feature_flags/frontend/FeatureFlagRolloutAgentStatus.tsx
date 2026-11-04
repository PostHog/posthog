import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { featureFlagRolloutAgentLogic } from './featureFlagRolloutAgentLogic'

export function FeatureFlagRolloutAgentStatus({ flagId }: { flagId: number }): JSX.Element | null {
    const logic = featureFlagRolloutAgentLogic({ id: flagId })
    const { latestPlan, plansLoading } = useValues(logic)
    const { stopPlan } = useActions(logic)

    if (!latestPlan) {
        return null
    }

    const steps = `${latestPlan.steps_applied} of ${latestPlan.percentages.length}`
    const taskLink = latestPlan.task_id ? (
        <Link to={urls.taskDetail(latestPlan.task_id)}>View the agent's work</Link>
    ) : null

    if (latestPlan.status === 'active') {
        return (
            <LemonBanner type="info">
                <div className="flex flex-col gap-1">
                    <strong>An agent is rolling out this flag</strong>
                    <span>
                        Steps done: {steps}. The approved percentages are {latestPlan.percentages.join(', ')}.
                    </span>
                    {latestPlan.next_check_at && (
                        <span>
                            Next check: <TZLabel time={latestPlan.next_check_at} />
                        </span>
                    )}
                    {latestPlan.last_summary && <span>Last result: {latestPlan.last_summary}</span>}
                    <div className="flex flex-wrap items-center gap-2 mt-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="feature-flag-rollout-agent-stop"
                            loading={plansLoading}
                            onClick={() => stopPlan(latestPlan.id)}
                        >
                            Stop rollout
                        </LemonButton>
                        {taskLink}
                    </div>
                </div>
            </LemonBanner>
        )
    }

    const stopped = latestPlan.status === 'stopped'
    return (
        <LemonBanner type={stopped ? 'warning' : 'success'} dismissKey={`feature-flag-rollout-agent-${latestPlan.id}`}>
            <div className="flex flex-col gap-1">
                <strong>{stopped ? 'The agent rollout stopped' : 'The agent rollout finished'}</strong>
                <span>
                    {stopped
                        ? `Steps done: ${steps}. The flag stays at its current percentage. ${latestPlan.stop_reason}`
                        : `The flag reached ${latestPlan.percentages[latestPlan.percentages.length - 1]}%.`}
                </span>
                {taskLink}
            </div>
        </LemonBanner>
    )
}
