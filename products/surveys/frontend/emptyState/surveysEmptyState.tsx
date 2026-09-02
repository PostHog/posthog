import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import { IconMessage } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { NewSurveyActions } from './NewSurveyActions'
import { SurveysPreview } from './SurveysPreview'
import { surveysSetupLogic } from './surveysSetupLogic'

const HedgehogReporter = pngHoggie(reporterPng)

export const surveysEmptyState: SceneProductEmptyState = {
    statusLogic: surveysSetupLogic,
    config: {
        productKey: ProductKey.SURVEYS,
        productName: 'Surveys',
        icon: <IconMessage />,
        accentColor: 'var(--color-product-surveys-light)',
        accentColorDark: 'var(--color-product-surveys-dark)',
        hedgehog: HedgehogReporter,
        text: {
            'needs-setup': {
                headline: 'Ask your users, right in the product',
                lead: 'Launch NPS, CSAT, or fully custom surveys with no code. Target them by cohort, feature flag, or URL, and analyze responses next to the rest of your product data.',
            },
        },
        PrimaryAction: NewSurveyActions,
        docsUrl: 'https://posthog.com/docs/surveys',
        previewLabel: 'Responses, once your survey is live',
        Preview: SurveysPreview,
        // Skipping would reveal a bare empty list; creating a survey is the only next step.
        skippable: false,
    },
}
