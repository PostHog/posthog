import * as experimentPng from '@posthog/brand/hoggies/png/experiment'
import { IconFlask } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

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
                lead: 'Split traffic between variants, measure the impact on the metrics you care about, and ship the winner. Statistical analysis is automatic, so you know when a result is real and when it is chance.',
            },
        },
        primaryAction: { label: 'Create your first experiment', to: urls.experiment('new') },
        docsUrl: 'https://posthog.com/docs/experiments',
        previewLabel: 'Your results, once running',
        Preview: ExperimentPreview,
    },
}
