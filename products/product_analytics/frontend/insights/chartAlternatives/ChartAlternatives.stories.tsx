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

const enabledParameters = {
    ...insightSceneStoryParameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
}

async function openGallery(canvasElement: HTMLElement): Promise<void> {
    const button = await waitFor(() => {
        const control = canvasElement.querySelector<HTMLElement>('[data-attr="chart-alternatives-all"]')
        if (!control || control.getAttribute('aria-disabled') === 'true') {
            throw new Error('Chart type control is not ready.')
        }
        return control
    })
    button.click()
    await waitFor(() => {
        const gallery = document.querySelector('[data-attr="chart-alternatives-gallery"]')
        if (!gallery || gallery.querySelector('.Spinner')) {
            throw new Error('Chart previews did not load.')
        }
    })
}

export const FlagOffBaseline: Story = createInsightStory(insight as unknown as QueryBasedInsightModel, 'edit')
FlagOffBaseline.parameters = {
    ...insightSceneStoryParameters,
    featureFlags: [],
}

export const EnabledDefault: Story = createInsightStory(insight as unknown as QueryBasedInsightModel, 'edit')
EnabledDefault.parameters = enabledParameters

export const EnabledGalleryOpen: Story = createInsightStory(insight as unknown as QueryBasedInsightModel, 'edit')
EnabledGalleryOpen.parameters = enabledParameters
EnabledGalleryOpen.play = async ({ canvasElement }): Promise<void> => openGallery(canvasElement)

const insightWithCountryBreakdown = {
    ...insight,
    query: {
        ...insight.query,
        source: {
            ...insight.query.source,
            series: [{ ...insight.query.source.series[0], math_property: 'duration' }],
            breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
        },
    },
}

export const EnabledGalleryOpenCountryBreakdown: Story = createInsightStory(
    insightWithCountryBreakdown as unknown as QueryBasedInsightModel,
    'edit'
)
EnabledGalleryOpenCountryBreakdown.parameters = enabledParameters
EnabledGalleryOpenCountryBreakdown.play = async ({ canvasElement }): Promise<void> => openGallery(canvasElement)
