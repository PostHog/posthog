import * as experimentPng from '@posthog/brand/hoggies/png/experiment'
import { IconFlask } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ExperimentPreview } from './ExperimentPreview'
import { experimentsSetupLogic } from './experimentsSetupLogic'

const HedgehogExperiment = pngHoggie(experimentPng)

export const experimentsEmptyState: SceneProductEmptyState = {
    statusLogic: experimentsSetupLogic,
    config: {
        productKey: ProductKey.EXPERIMENTS,
        productName: 'Experiments',
        icon: <IconFlask />,
        accentColor: 'var(--color-product-experiments-light)',
        hedgehog: HedgehogExperiment,
        text: {
            'needs-setup': {
                headline: 'Test changes on real users before you commit',
                lead: 'Split traffic between variants and measure the impact on the metrics you care about. Choose Bayesian or frequentist statistics, keep a holdout to track long-term impact, and reuse shared metrics across experiments. Run no-code experiments on your site, or test anything a flag can gate, LLM prompts included.',
            },
        },
        primaryAction: {
            label: 'Create your first experiment',
            to: urls.experiment('new'),
            accessControl: {
                resourceType: AccessControlResourceType.Experiment,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'create-experiment',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/experiments',
        previewLabel: 'Your results, once running',
        Preview: ExperimentPreview,
    },
}
