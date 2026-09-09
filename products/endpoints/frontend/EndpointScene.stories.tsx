import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { endpointSceneLogic } from './endpointSceneLogic'

const endpoint = {
    id: 'example-endpoint-id',
    name: 'weekly-pageviews',
    description: 'Page views by week',
    current_version: 2,
    version: 2,
    is_active: true,
    is_materialized: false,
    data_freshness_seconds: 86400,
    endpoint_path: '/api/projects/997/endpoints/weekly-pageviews/run',
    query: {
        kind: 'HogQLQuery',
        query: 'SELECT toStartOfWeek(timestamp) AS week, count() AS views FROM events GROUP BY week',
    },
    materialization: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_executed_at: null,
    tags: [],
}

const meta: Meta = {
    title: 'Scenes-App/Endpoints/AI',
    component: App,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/endpoints': () => [200, { results: [endpoint], count: 1 }],
                '/api/environments/:team_id/endpoints/:name': () => [200, endpoint],
                '/api/environments/:team_id/endpoints/:name/versions': () => [200, { results: [endpoint], count: 1 }],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        pageUrl: `${urls.endpoint(endpoint.name)}?tab=versions`,
        featureFlags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
        testOptions: { waitForSelector: '[data-attr="endpoint-ask-ai"]', viewport: { width: 1280, height: 900 } },
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const Versions: Story = {}

export const UnsavedChanges: Story = {
    render: function UnsavedChangesStory() {
        const { endpoint: loadedEndpoint } = useValues(endpointSceneLogic)
        const { setDataFreshness, endpointChangedByAgent } = useActions(endpointSceneLogic)
        useEffect(() => {
            if (loadedEndpoint?.name === endpoint.name) {
                setDataFreshness(3600)
                endpointChangedByAgent(endpoint.name)
            }
        }, [loadedEndpoint, setDataFreshness, endpointChangedByAgent])
        return <App />
    },
}
