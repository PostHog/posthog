import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import {
    createInsightStory,
    insightSceneMswDecorator,
    insightSceneStoryParameters,
} from 'scenes/insights/__mocks__/createInsightScene'

import insight from '~/mocks/fixtures/api/projects/team_id/insights/editorFiltersLongValue.json'
import type { QueryBasedInsightModel } from '~/types'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Scenes-App/Insights/Chart alternatives',
    parameters: insightSceneStoryParameters,
    decorators: [insightSceneMswDecorator],
}

export default meta

export const FlagOffBaseline: Story = createInsightStory(insight as unknown as QueryBasedInsightModel, 'edit')
FlagOffBaseline.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [],
}

export const EnabledDefault: Story = createInsightStory(insight as unknown as QueryBasedInsightModel, 'edit')
EnabledDefault.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
}

const insightWithBreakdown = {
    ...insight,
    query: {
        ...insight.query,
        source: {
            ...insight.query.source,
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
        },
    },
}

export const EnabledWithBreakdown: Story = createInsightStory(
    insightWithBreakdown as unknown as QueryBasedInsightModel,
    'edit'
)
EnabledWithBreakdown.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
}

const insightWithNumericProperty = {
    ...insight,
    query: {
        ...insight.query,
        source: {
            ...insight.query.source,
            series: [{ ...insight.query.source.series[0], math_property: 'duration' }],
        },
    },
}

export const EnabledNumericProperty: Story = createInsightStory(
    insightWithNumericProperty as unknown as QueryBasedInsightModel,
    'edit'
)
EnabledNumericProperty.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
}

const insightWithCountryBreakdown = {
    ...insightWithNumericProperty,
    query: {
        ...insightWithNumericProperty.query,
        source: {
            ...insightWithNumericProperty.query.source,
            breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
        },
    },
}

export const EnabledCountryBreakdown: Story = createInsightStory(
    insightWithCountryBreakdown as unknown as QueryBasedInsightModel,
    'edit'
)
EnabledCountryBreakdown.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
}

export const EnabledNarrowScene: Story = createInsightStory(
    insight as unknown as QueryBasedInsightModel,
    'edit',
    false,
    {
        openSidePanel: true,
    }
)
EnabledNarrowScene.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
    testOptions: {
        ...insightSceneStoryParameters.testOptions,
        viewport: { width: 1280, height: 720 },
    },
}

export const EnabledGalleryOpen: Story = createInsightStory(insight as unknown as QueryBasedInsightModel, 'edit')
EnabledGalleryOpen.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
}
EnabledGalleryOpen.play = async ({ canvasElement }): Promise<void> => {
    const button = await waitFor(() => {
        const control = canvasElement.querySelector<HTMLElement>('[data-attr="chart-alternatives-all"]')
        if (!control || control.getAttribute('aria-disabled') === 'true') {
            throw new Error('Chart alternatives control is not ready.')
        }
        return control
    })
    button.click()
    await waitFor(() => {
        if (!document.querySelector('[data-attr="chart-alternatives-gallery"]')) {
            throw new Error('Chart types did not open.')
        }
    })
}
