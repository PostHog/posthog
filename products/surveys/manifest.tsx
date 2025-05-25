import { IconMessage } from '@posthog/icons'
import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Surveys',
    urls: {
        surveys: (tab?: SurveysTabs): string => `/surveys${tab ? `?tab=${tab}` : ''}`,
        /** @param id A UUID or 'new'. ':id' for routing. */
        survey: (id: string): string => `/surveys/${id}`,
        surveyTemplates: (): string => '/survey_templates',
    },
    fileSystemTypes: {
        survey: {
            icon: <IconMessage />,
            href: (ref: string) => urls.survey(ref),
            iconColor: ['var(--product-surveys-primary)', 'var(--product-surveys-primary)'],
        },
    },
    treeItemsNew: [
        {
            path: `Survey`,
            type: 'survey',
            href: urls.survey('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: 'Surveys',
            type: 'survey',
            href: urls.surveys(),
            visualOrder: PRODUCT_VISUAL_ORDER.surveys,
        },
    ],
}
