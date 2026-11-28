import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { replayScannersStoryConfig } from '../__mocks__/replayScannersStoryConfig'
import {
    digestScoutConfig,
    experimentScanner,
    readyAnalysis,
    scopedSummarizerScanner,
    variantsDecorator,
    variantsReadout,
} from '../__mocks__/replayScannersStoryFixtures'
import type { ExperimentVariantsReadoutApi } from '../generated/api.schemas'

const meta: Meta = {
    ...replayScannersStoryConfig,
    component: App,
    title: 'Scenes-App/Replay Vision',
}
export default meta

const withoutAnalysis = (readout: ExperimentVariantsReadoutApi): ExperimentVariantsReadoutApi => ({
    ...readout,
    variants: readout.variants.map((variant) => ({ ...variant, digest: null, analysis_observations: null })),
    differences: null,
})

// The experiment scanner's variant analysis scout, so the Variants tab offers Run now.
const variantAnalysisScoutMocks = mswDecorator({
    get: {
        '/api/projects/:team_id/signals/scout/configs/': [
            {
                ...digestScoutConfig,
                id: '00000000-0000-0000-0000-0000000000c9',
                skill_name: 'signals-scout-post-exposure-friction-variant-analysis',
                display_name: 'Post-exposure friction / variant analysis',
                description: 'Compares what users in each experiment variant do.',
                source_id: experimentScanner.id,
                tags: ['replay-vision-variant-analysis'],
            },
        ],
    },
})

export const ExperimentVariants: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(variantsReadout()), variantAnalysisScoutMocks],
}

// The same scanner with its experiment in the `scope` column instead of the experiment type's
// config. Everything the experiment drives has to look the same: the Variants tab is offered, the
// recordings banner names the experiment, and the observations table filters by variant. Reading
// the type instead of the scope hides all three.
export const ExperimentVariantsFromScope: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(scopedSummarizerScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(variantsReadout(), scopedSummarizerScanner), variantAnalysisScoutMocks],
}

// No variant analysis scout yet: the counts show, and the comparison offers to set one up.
export const ExperimentVariantsNoScout: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(withoutAnalysis(variantsReadout({ analysis: null })))],
}

export const ExperimentVariantsFirstRunPending: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        variantsDecorator(withoutAnalysis(variantsReadout({ analysis: { ...readyAnalysis, recorded_at: null } }))),
        variantAnalysisScoutMocks,
    ],
}

// Before the first observation: each variant shows where its themes and observations will go.
export const ExperimentVariantsWaitingForObservations: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        variantsDecorator(
            withoutAnalysis(
                variantsReadout({
                    analysis: { ...readyAnalysis, recorded_at: null },
                    window: { total_observations: 0, first_observation_at: null, last_observation_at: null },
                    unattributed_count: 0,
                    variants: variantsReadout().variants.map((variant) => ({
                        ...variant,
                        observations: 0,
                        distinct_people: 0,
                        median_session_duration_s: null,
                        sampling_rate: null,
                        latest_observations: [],
                    })),
                })
            )
        ),
    ],
}

export const ExperimentVariantsThreeVariants: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        variantsDecorator(
            variantsReadout({
                window: { ...variantsReadout().window, total_observations: 99 },
                variants: [
                    ...variantsReadout().variants,
                    {
                        ...variantsReadout().variants[1],
                        key: 'test-compact',
                        observations: 28,
                        distinct_people: 27,
                        sampling_rate: 0.45,
                        digest: null,
                        latest_observations: [],
                    },
                ],
            })
        ),
    ],
}

// About 520px of scene, the width a laptop leaves with the side panel open. The nav collapses at
// this viewport, so the scene takes the whole window less its padding.
export const ExperimentVariantsNarrow: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
        testOptions: { viewport: { width: 560, height: 1800 } },
    },
    decorators: [variantsDecorator(variantsReadout())],
}
