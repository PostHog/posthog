import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'

import type { FeatureFlagRolloutSummaryApi } from './generated/api.schemas'

// The status endpoint returns reasons without terminating punctuation, and the banner reads them
// next to sentences written here.
function asSentence(reason: string): string {
    const trimmed = reason.trim()
    if (!trimmed || /[.!?]$/.test(trimmed)) {
        return trimmed
    }
    return `${trimmed}.`
}

// Rollout is supporting detail, not a second verdict on staleness. Branch order matters here:
// `effectively_full_rollout` and `has_targeting_conditions` can both be true for a multivariate
// flag, because one 100% condition plus one 100% variant satisfies the full-rollout check while a
// separate targeted condition above it serves a different variant. Reading full rollout first would
// claim one result for every user while targeted users get another.
function rolloutSentence(rollout: FeatureFlagRolloutSummaryApi | undefined, hasUsageData: boolean): string | null {
    if (!rollout || rollout.max_rollout_percentage === null) {
        // A flag with no release conditions. `effectively_full_rollout` is true for this shape, so
        // naming a condition that rolls out to everyone would describe something that is not there.
        return null
    }
    const percentage = rollout.max_rollout_percentage

    if (rollout.has_targeting_conditions) {
        return `Its highest rollout is ${percentage}% inside a targeted release condition. That is not ${percentage}% of all users.`
    }
    if (rollout.effectively_full_rollout) {
        // Without usage data the backend reaches its stale verdict from the rollout itself, so
        // `reason` already says the flag always resolves one way. Saying it again adds nothing.
        return hasUsageData ? 'One release condition rolls out to everyone, so every user gets the same result.' : null
    }
    if (percentage < 100) {
        return `Its rollout is ${percentage}% of all users.`
    }
    // A rollout that covers everyone without meeting the full-rollout check, which happens when a
    // multivariate flag splits a 100% condition across variants.
    return rollout.is_multivariate ? 'It rolls out to all users, split across its variants.' : null
}

export function FeatureFlagStaleBanner(): JSX.Element | null {
    const { showStaleFlagBanner, flagStatus, featureFlag, hasExperiment, dependentFlags } = useValues(featureFlagLogic)
    const { setSelectedTab } = useActions(featureFlagLogic)

    if (!showStaleFlagBanner || !flagStatus) {
        return null
    }

    const rollout = rolloutSentence(flagStatus.rollout, Boolean(featureFlag.last_called_at))

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
                    {asSentence(flagStatus.reason)}
                    {rollout ? ` ${rollout}` : ''}
                </span>
                {hasExperiment && <span>This flag is linked to an experiment.</span>}
                {dependentFlags.length > 0 && <span>Other flags depend on this flag.</span>}
                <span>Review usage and code references before disabling or archiving this flag.</span>
            </div>
        </LemonBanner>
    )
}
