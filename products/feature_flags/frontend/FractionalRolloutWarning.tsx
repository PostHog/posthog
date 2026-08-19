import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { FeatureFlagEvaluationRuntime, FeatureFlagGroupType } from '~/types'

/** First SDK releases that deserialize a fractional rollout percentage. */
const MIN_DOTNET_VERSION = '2.13.3'
const MIN_JAVA_VERSION = '2.12.1'

/** Release-condition rollout percentages that aren't whole numbers.
 *
 *  Ignores multivariate variant rollouts on purpose: the SDKs that typed rollout percentages as
 *  integers only did so for the condition group field, so fractional variant splits, which an even
 *  three-way split can't avoid, parse everywhere. */
export function fractionalRolloutPercentages(filterGroups: FeatureFlagGroupType[] | undefined): number[] {
    return (filterGroups ?? [])
        .map((group) => group.rollout_percentage)
        .filter((percentage): percentage is number => typeof percentage === 'number' && !Number.isInteger(percentage))
}

/** Warns that a fractional release-condition rollout breaks local evaluation on older SDKs. */
export function FractionalRolloutWarning({
    filterGroups,
    evaluationRuntime = FeatureFlagEvaluationRuntime.ALL,
    className,
}: {
    filterGroups: FeatureFlagGroupType[] | undefined
    evaluationRuntime?: FeatureFlagEvaluationRuntime
    className?: string
}): JSX.Element | null {
    // Local evaluation only runs in server-side SDKs, so a client-only flag can't hit this.
    if (evaluationRuntime === FeatureFlagEvaluationRuntime.CLIENT) {
        return null
    }

    const percentages = fractionalRolloutPercentages(filterGroups)
    if (percentages.length === 0) {
        return null
    }

    return (
        <LemonBanner type="warning" className={className}>
            This flag has a fractional rollout percentage ({percentages.join('%, ')}%). The .NET and Java server-side
            SDKs read rollout percentages as whole numbers before .NET {MIN_DOTNET_VERSION} and Java {MIN_JAVA_VERSION}.
            On an older version the flag definitions payload fails to parse, so local evaluation stops working for{' '}
            <strong>every flag in the project</strong> and each evaluation goes to the <code>/flags</code> endpoint
            instead. Upgrade those SDKs, or use a whole number here.{' '}
            <Link to="https://posthog.com/docs/feature-flags/local-evaluation" target="_blank">
                Learn more about local evaluation
            </Link>
        </LemonBanner>
    )
}
