import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { FeatureFlagGroupType } from '~/types'

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

/** Trims a stored rollout to something readable. A flag saved through the API can carry far more
 *  precision than the editor's two decimal places, and 33.333333333333336 reads as a bug rather
 *  than a warning. Significant digits rather than fixed decimals, so a sub-0.01 rollout such as
 *  0.00015 doesn't render as 0. */
function formatPercentage(percentage: number): string {
    return `${Number(percentage.toPrecision(4))}%`
}

/** Warns that a fractional release-condition rollout breaks local evaluation on older SDKs.
 *
 *  Not gated on the flag's evaluation runtime: the local evaluation payload carries client-only flags
 *  too (SDKs filter by runtime only after parsing), so even a client-only flag breaks the parse. */
export function FractionalRolloutWarning({
    filterGroups,
    className,
}: {
    filterGroups: FeatureFlagGroupType[] | undefined
    className?: string
}): JSX.Element | null {
    const percentages = fractionalRolloutPercentages(filterGroups)
    if (percentages.length === 0) {
        return null
    }

    const formatted = percentages.map(formatPercentage).join(', ')

    return (
        <LemonBanner type="warning" className={className}>
            {percentages.length === 1
                ? `This flag has a fractional rollout percentage (${formatted}).`
                : `This flag has fractional rollout percentages (${formatted}).`}{' '}
            The .NET and Java server-side SDKs read rollout percentages as whole numbers before .NET{' '}
            {MIN_DOTNET_VERSION} and Java {MIN_JAVA_VERSION}. On an older version the flag definitions payload fails to
            parse, so local evaluation stops working for <strong>every flag in the project</strong> and each evaluation
            goes to the <code>/flags</code> endpoint instead. Upgrade those SDKs, or change the rollout to a whole
            number.{' '}
            <Link to="https://posthog.com/docs/feature-flags/local-evaluation" target="_blank">
                Learn more about local evaluation
            </Link>
        </LemonBanner>
    )
}
