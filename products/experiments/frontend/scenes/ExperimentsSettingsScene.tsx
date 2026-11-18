import { useValues } from 'kea'

import { Heading, Skeleton, Text } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

import { MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'products/experiments/frontend/constants'

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

function QuillSettingsSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <Heading size="base" render={<h2 className="m-0" />}>
                    {title}
                </Heading>
                {description && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {description}
                    </Text>
                )}
            </div>
            {children}
        </section>
    )
}

function QuillSettingsItem({
    label,
    description,
    children,
}: {
    label?: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            {label && (
                <Text size="sm" weight="medium" render={<span />}>
                    {label}
                </Text>
            )}
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                {description}
            </Text>
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
    const quill =
        !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] && !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_RESULTS_REDESIGN]
    const Section = quill ? QuillSettingsSection : SettingsSection
    const Item = quill ? QuillSettingsItem : SettingsItem

    // The cleanup PR runs as a PostHog Desktop task, so the setting is only relevant with
    // Code access (same gate as the end-experiment modal checkbox).
    const cleanupPrAvailable = !!featureFlags[FEATURE_FLAGS.TASKS]

    if (experimentsConfigLoading && !experimentsConfig) {
        return quill ? (
            <div className="flex flex-col gap-4">
                <Skeleton className="h-6 w-1/3" />
                <Skeleton className="h-24 w-full" />
            </div>
        ) : (
            <SpinnerOverlay sceneLevel />
        )
    }

    return (
        <div className="space-y-8">
            <Section
                title="Statistical analysis"
                description="Defaults for new experiments in this environment. Each setting can be overridden per experiment."
            >
                <Item label="Statistical method" description="The statistical method used to analyze results.">
                    <DefaultExperimentStatsMethod />
                </Item>
                <Item
                    label="Confidence level"
                    description="Higher confidence levels reduce false positives but require more data."
                >
                    <DefaultExperimentConfidenceLevel />
                </Item>
                <Item
                    label="Minimum detectable effect"
                    description="The smallest effect size you want to detect with statistical significance. Lower values require more data and longer run times."
                >
                    <DefaultMinimumDetectableEffect />
                </Item>
                <Item
                    label="Conversion window"
                    description="When enabled, new experiments exclude participants whose conversion or retention window hasn't elapsed yet."
                >
                    <DefaultOnlyCountMaturedUsers />
                </Item>
            </Section>
            <Section
                title="CUPED variance reduction"
                description="CUPED uses pre-experiment data to detect significant effects faster on supported metrics. Can be overridden per experiment."
            >
                <DefaultCupedEnabled />
                <Item
                    label="Lookback window"
                    description={`Number of days before the experiment start to use as the pre-experiment window. Must be between ${MIN_LOOKBACK_DAYS} and ${MAX_LOOKBACK_DAYS} days.`}
                >
                    <DefaultCupedLookbackDays />
                </Item>
            </Section>
            <Section
                title="Sequential testing"
                description="Sequential testing produces always-valid p-values that are robust to peeking. Confidence intervals are wider in exchange. Only applies to the frequentist statistical method. Can be overridden per experiment."
            >
                <DefaultSequentialTestingEnabled />
                <Item
                    label="Tuning parameter"
                    description="Roughly the sample size at which the always-valid confidence sequence is tightest. Set close to the expected total sample size of new experiments to minimize the width penalty."
                >
                    <DefaultSequentialTuningParameter />
                </Item>
            </Section>
            <Section title="Recalculation">
                <Item
                    label="Daily recalculation time"
                    description="The time of day when experiment time series are recalculated, in your project's timezone."
                >
                    <ExperimentRecalculationTime />
                </Item>
            </Section>
            {cleanupPrAvailable && (
                <Section title="Flag cleanup">
                    <Item
                        label="Default repository for flag cleanup PRs"
                        description="Used when an experiment doesn't have its own repository."
                    >
                        <FlagCleanupRepository />
                    </Item>
                </Section>
            )}
        </div>
    )
}
