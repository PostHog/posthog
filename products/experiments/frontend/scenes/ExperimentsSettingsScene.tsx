import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'scenes/experiments/constants'
import { DefaultMinimumDetectableEffect } from 'scenes/experiments/DefaultMinimumDetectableEffect'
import { DefaultCupedEnabled } from 'scenes/settings/environment/DefaultCupedEnabled'
import { DefaultCupedLookbackDays } from 'scenes/settings/environment/DefaultCupedLookbackDays'
import { DefaultExperimentConfidenceLevel } from 'scenes/settings/environment/DefaultExperimentConfidenceLevel'
import { DefaultExperimentStatsMethod } from 'scenes/settings/environment/DefaultExperimentStatsMethod'
import { DefaultOnlyCountMaturedUsers } from 'scenes/settings/environment/DefaultOnlyCountMaturedUsers'
import { DefaultSequentialTestingEnabled } from 'scenes/settings/environment/DefaultSequentialTestingEnabled'
import { DefaultSequentialTuningParameter } from 'scenes/settings/environment/DefaultSequentialTuningParameter'
import { ExperimentRecalculationTime } from 'scenes/settings/environment/ExperimentRecalculationTime'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'
import { FlagCleanupRepository } from 'scenes/settings/environment/FlagCleanupRepository'

function SettingsSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            <h2 className="text-base font-semibold mb-0">{title}</h2>
            {description && <p className="text-secondary mt-1 mb-0">{description}</p>}
            <div className="space-y-4 mt-4">{children}</div>
        </div>
    )
}

function SettingsItem({
    label,
    description,
    children,
}: {
    label?: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            {label && <LemonLabel>{label}</LemonLabel>}
            <p className="text-secondary text-sm mt-1">{description}</p>
            {children}
        </div>
    )
}

/**
 * although this works fine for now, if we keep adding more settings we need to refactor this to use the
 * <Settings /> component. That will require we create a new section for experiments on the SettingsMap.
 */
export function ExperimentsSettingsScene(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // The cleanup PR runs as a PostHog Desktop task, so the setting is only relevant with
    // Code access on top of the rollout flag (same gate as the end-experiment modal checkbox).
    const cleanupPrAvailable =
        !!featureFlags[FEATURE_FLAGS.EXPERIMENT_FLAG_CLEANUP_PR] && !!featureFlags[FEATURE_FLAGS.TASKS]

    if (experimentsConfigLoading && !experimentsConfig) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <div className="space-y-8">
            <SettingsSection
                title="Statistical analysis"
                description="Defaults for new experiments in this environment. Each setting can be overridden per experiment."
            >
                <SettingsItem label="Statistical method" description="The statistical method used to analyze results.">
                    <DefaultExperimentStatsMethod />
                </SettingsItem>
                <SettingsItem
                    label="Confidence level"
                    description="Higher confidence levels reduce false positives but require more data."
                >
                    <DefaultExperimentConfidenceLevel />
                </SettingsItem>
                <SettingsItem
                    label="Minimum detectable effect"
                    description="The smallest effect size you want to detect with statistical significance. Lower values require more data and longer run times."
                >
                    <DefaultMinimumDetectableEffect />
                </SettingsItem>
                <SettingsItem
                    label="Conversion window"
                    description="When enabled, new experiments exclude participants whose conversion or retention window hasn't elapsed yet."
                >
                    <DefaultOnlyCountMaturedUsers />
                </SettingsItem>
            </SettingsSection>
            <SettingsSection
                title="CUPED variance reduction"
                description="CUPED uses pre-experiment data to detect significant effects faster on supported metrics. Can be overridden per experiment."
            >
                <DefaultCupedEnabled />
                <SettingsItem
                    label="Lookback window"
                    description={`Number of days before the experiment start to use as the pre-experiment window. Must be between ${MIN_LOOKBACK_DAYS} and ${MAX_LOOKBACK_DAYS} days.`}
                >
                    <DefaultCupedLookbackDays />
                </SettingsItem>
            </SettingsSection>
            <SettingsSection
                title="Sequential testing"
                description="Sequential testing produces always-valid p-values that are robust to peeking. Confidence intervals are wider in exchange. Only applies to the frequentist statistical method. Can be overridden per experiment."
            >
                <DefaultSequentialTestingEnabled />
                <SettingsItem
                    label="Tuning parameter"
                    description="Roughly the sample size at which the always-valid confidence sequence is tightest. Set close to the expected total sample size of new experiments to minimize the width penalty."
                >
                    <DefaultSequentialTuningParameter />
                </SettingsItem>
            </SettingsSection>
            <SettingsSection title="Recalculation">
                <SettingsItem
                    label="Daily recalculation time"
                    description="The time of day when experiment metrics are recalculated, in your project's timezone."
                >
                    <ExperimentRecalculationTime />
                </SettingsItem>
            </SettingsSection>
            {cleanupPrAvailable && (
                <SettingsSection title="Flag cleanup">
                    <SettingsItem
                        label="Default repository for flag cleanup PRs"
                        description="Used when an experiment doesn't have its own repository."
                    >
                        <FlagCleanupRepository />
                    </SettingsItem>
                </SettingsSection>
            )}
        </div>
    )
}
