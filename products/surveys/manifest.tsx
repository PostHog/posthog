import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Surveys',
    urls: {
        surveys: (tab?: SurveysTabs): string => `/surveys${tab ? `?tab=${tab}` : ''}`,
        /** @param id A UUID or 'new'. ':id' for routing. */
        survey: (id: string): string => `/surveys/${id}`,
        surveyTemplates: (): string => '/survey_templates',
        surveyWizard: (id: string = 'new'): string => `/surveys/guided/${id}`,
    },
    fileSystemTypes: {
        survey: {
            name: 'Survey',
            iconType: 'survey',
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
            iconType: 'survey',
            iconColor: ['var(--color-product-surveys-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Surveys',
            intents: [ProductKey.SURVEYS],
            category: 'Behavior',
            type: 'survey',
            href: urls.surveys(),
            iconType: 'survey',
            iconColor: ['var(--color-product-surveys-light)'] as FileSystemIconColor,
            sceneKey: 'Surveys',
            sceneKeys: ['Survey', 'Surveys'],
        },
    ],
}
