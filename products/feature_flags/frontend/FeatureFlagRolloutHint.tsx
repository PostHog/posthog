import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCopy, IconSparkles } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { featureFlagRolloutAgentLogic } from './featureFlagRolloutAgentLogic'
import { FeatureFlagRolloutAgentModal } from './FeatureFlagRolloutAgentModal'
import { featureFlagRolloutPlanLogic } from './featureFlagRolloutPlanLogic'

function FeatureFlagRolloutHintBanner({
    flagId,
    flagKey,
    currentProjectId,
}: {
    flagId: number
    flagKey: string
    currentProjectId: number | null
}): JSX.Element | null {
    const logic = featureFlagRolloutPlanLogic({ id: flagId })
    const { isAiPlanAvailable, planStarted } = useValues(logic)
    const { startPlan, copyAgentPrompt } = useActions(logic)
    const agentLogic = featureFlagRolloutAgentLogic({ id: flagId })
    const { isAgentRolloutAvailable, activePlan } = useValues(agentLogic)
    const { openSetupModal } = useActions(agentLogic)

    if (activePlan) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            dismissKey="feature-flag-rollout-hint"
            onClose={() => posthog.capture('feature flag rollout hint dismissed', { flag_id: flagId })}
        >
            <div className="flex flex-col gap-1">
                <strong>Rolling this flag out gradually?</strong>
                {isAgentRolloutAvailable ? (
                    <span>
                        A PostHog AI agent can run the rollout for you. You set the percentages, the time between steps,
                        and the results that count as healthy, and you approve them once. The agent checks the results
                        before each step, and if a check fails, the rollout stops and you get a notification.
                    </span>
                ) : (
                    <span>
                        An AI agent can plan the steps with you. It asks which insights or dashboards show whether the
                        feature is healthy and offers to create a dashboard if you have none. It doesn't keep running
                        between steps, so come back to it, or ask it to set a reminder. It checks the results each time,
                        and you approve every step.
                    </span>
                )}
                <span>
                    The copied prompt works in any agent connected to the{' '}
                    <Link to="https://posthog.com/docs/model-context-protocol" target="_blank">
                        PostHog MCP server
                    </Link>
                    .
                </span>
                <div className="flex flex-wrap gap-2 mt-1">
                    {isAgentRolloutAvailable ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconSparkles />}
                            data-attr="feature-flag-rollout-hint-agent"
                            onClick={openSetupModal}
                        >
                            Set up an agent rollout
                        </LemonButton>
                    ) : (
                        isAiPlanAvailable && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                data-attr="feature-flag-rollout-hint-plan"
                                disabledReason={planStarted ? 'Plan started. Continue in PostHog AI.' : undefined}
                                onClick={() => startPlan(flagKey, currentProjectId)}
                            >
                                Plan with PostHog AI
                            </LemonButton>
                        )
                    )}
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCopy />}
                        data-attr="feature-flag-rollout-hint-copy-prompt"
                        onClick={() => copyAgentPrompt(flagKey, currentProjectId)}
                    >
                        Copy prompt for your agent
                    </LemonButton>
                </div>
            </div>
            <FeatureFlagRolloutAgentModal flagId={flagId} />
        </LemonBanner>
    )
}

export function FeatureFlagRolloutHint(): JSX.Element | null {
    const { showRolloutHint, featureFlag, currentProjectId } = useValues(featureFlagLogic)

    if (!showRolloutHint || !featureFlag.id) {
        return null
    }

    return (
        <FeatureFlagRolloutHintBanner
            flagId={featureFlag.id}
            flagKey={featureFlag.key}
            currentProjectId={currentProjectId}
        />
    )
}
