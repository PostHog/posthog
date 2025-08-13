import { IconMessage } from '@posthog/icons'
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
            name: 'Survey',
            icon: <IconMessage />,
            href: (ref: string) => urls.survey(ref),
            iconColor: ['var(--color-product-surveys-light)'],
            filterKey: 'survey',
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
            category: 'Behavior',
            type: 'survey',
            href: urls.surveys(),
        },
    ],
}
