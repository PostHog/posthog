import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { endWithPunctation } from 'lib/utils/strings'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'

import { formatPercentage } from './FractionalRolloutWarning'
import type { FeatureFlagRolloutSummaryApi } from './generated/api.schemas'

// Rollout is supporting detail, not a second verdict on staleness. Every line states only what the
// summary establishes, because the summary reads `filters.groups` and `filters.multivariate` and
// nothing else. It cannot see evaluation order, early exit, or which variant a condition overrides.
// Targeting is checked before full rollout: both can be true for a multivariate flag, and the
// targeted case is the one the reader needs.
// `targets` is the flag's aggregation unit (people, or a group noun like "organizations"), so a
// flag evaluated on groups does not report its rollout as a share of users.
function rolloutSentence(
    rollout: FeatureFlagRolloutSummaryApi | undefined,
    reasonStatesRollout: boolean,
    targets: string
): string | null {
    if (!rollout || rollout.max_rollout_percentage === null) {
        // A flag with no release conditions. `effectively_full_rollout` is true for this shape, so
        // naming a condition that rolls out to everyone would describe something that is not there.
        return null
    }
    const percentage = formatPercentage(rollout.max_rollout_percentage)

    if (rollout.has_targeting_conditions) {
        // The two fields are computed independently over the whole condition list.
        // `has_targeting_conditions` means some condition has property filters, and
        // `max_rollout_percentage` is the maximum across every condition. They need not describe the
        // same condition, so the banner reports the number without saying which one produced it.
        // When the reason already states the rollout, repeating it adds nothing.
        return reasonStatesRollout
            ? null
            : `Its highest rollout across release conditions is ${percentage}. Some conditions target specific ${targets}, so this may not be ${percentage} of all ${targets}.`
    }
    if (rollout.max_rollout_percentage < 100) {
        // `effectively_full_rollout` needs a condition at an explicit 100, so it implies a maximum
        // of 100 and cannot be true here.
        return `Its rollout is ${percentage} of all ${targets}.`
    }
    // A condition with no property filters covers everyone, at an explicit 100% or with the
    // percentage omitted, which evaluates to 100% at runtime. The banner stops there rather than
    // saying everyone gets the same result, which the summary cannot establish: with early exit an
    // earlier partial condition short-circuits the rest, and another condition can override the
    // variant. When the reason already states the rollout, repeating it adds nothing.
    return reasonStatesRollout ? null : `One release condition rolls out to all ${targets}.`
}

export function FeatureFlagStaleBanner(): JSX.Element | null {
    const { showStaleFlagBanner, flagStatus, hasExperiment, dependentFlags, aggregationTargetName } =
        useValues(featureFlagLogic)
    const { setSelectedTab } = useActions(featureFlagLogic)

    if (!showStaleFlagBanner || !flagStatus) {
        return null
    }

    const rollout = rolloutSentence(flagStatus.rollout, flagStatus.reason_states_rollout, aggregationTargetName)

    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'View usage',
                'data-attr': 'feature-flag-stale-banner-view-usage',
                onClick: () => {
                    posthog.capture('feature flag stale banner view usage clicked')
                    setSelectedTab(FeatureFlagsTab.USAGE)
                },
            }}
        >
            <div className="flex flex-col gap-1">
                <strong>This flag may no longer be needed</strong>
                <span>
                    {endWithPunctation(flagStatus.reason)}
                    {rollout ? ` ${rollout}` : ''}
                </span>
                {hasExperiment && <span>This flag is linked to an experiment.</span>}
                {dependentFlags.length > 0 && <span>Other flags depend on this flag.</span>}
                <span>Review usage and code references before disabling or archiving this flag.</span>
            </div>
        </LemonBanner>
    )
}
