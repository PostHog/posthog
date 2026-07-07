import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { EndpointConfiguration } from './endpoint-tabs/EndpointConfiguration'
import { endpointLogic } from './endpointLogic'
import { endpointSceneLogic } from './endpointSceneLogic'
import type { EndpointMaterializationSuggestionApi } from './generated/api.schemas'

const BLOCKED_REASON = 'Variables not supported: Variables in OR conditions are not supported for materialization'

const ORIGINAL_QUERY = `SELECT toStartOfDay(timestamp) AS day, count() AS purchases
FROM events
WHERE event = 'purchase'
  AND (properties.product_type = {variables.product_type} OR 0 = 1)
GROUP BY day`

const SUGGESTED_QUERY = `SELECT toStartOfDay(timestamp) AS day, count() AS purchases
FROM events
WHERE event = 'purchase'
  AND properties.product_type = {variables.product_type}
GROUP BY day`

const ENDPOINT = {
    id: '01936b3a-0000-0000-0000-000000000001',
    name: 'purchases-by-type',
    description: 'Daily purchase counts by product type',
    query: {
        kind: 'HogQLQuery',
        query: ORIGINAL_QUERY,
        variables: {
            'var-1': { variableId: 'var-1', code_name: 'product_type', value: 'all' },
        },
    },
    is_active: true,
    endpoint_path: '/api/projects/1/endpoints/purchases-by-type/run',
    url: null,
    ui_url: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    created_by: null,
    data_freshness_seconds: 86400,
    is_materialized: false,
    current_version: 1,
    current_version_id: '01936b3a-0000-0000-0000-000000000002',
    versions_count: 1,
    derived_from_insight: null,
    last_executed_at: null,
    materialization: {
        name: 'purchases-by-type',
        can_materialize: false,
        reason: BLOCKED_REASON,
    },
    bucket_overrides: null,
    columns: [],
    tags: [],
}

const suggestionOk: EndpointMaterializationSuggestionApi = {
    suggestion_status: 'ok',
    suggested_query: SUGGESTED_QUERY,
    explanation:
        'The `OR 0 = 1` branch is always false, so removing it leaves an equivalent query with the variable out of an OR context — which is what materialization requires.',
    attempts: 1,
    error: null,
    original_reason: BLOCKED_REASON,
}

const suggestionCannotFix: EndpointMaterializationSuggestionApi = {
    suggestion_status: 'cannot_fix',
    suggested_query: null,
    explanation:
        'The variable is compared against two different columns, so there is no single column the materialized table could key on without changing the results.',
    attempts: 1,
    error: null,
    original_reason: BLOCKED_REASON,
}

const suggestionFailed: EndpointMaterializationSuggestionApi = {
    suggestion_status: 'invalid',
    suggested_query: SUGGESTED_QUERY,
    explanation: null,
    attempts: 3,
    error: 'Variables in OR conditions are not supported for materialization',
    original_reason: BLOCKED_REASON,
}

const meta: Meta = {
    title: 'Products/Endpoints/MaterializationSuggestion',
    component: EndpointConfiguration,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.ENDPOINTS_AI_MATERIALIZATION_FIX],
    },
}
export default meta

type StoryProps = {
    suggestion: EndpointMaterializationSuggestionApi
    openModal: boolean
}

const Template: StoryFn<StoryProps> = ({ suggestion, openModal }) => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/endpoints/:name/': ENDPOINT,
            '/api/environments/:team_id/endpoints/:name/versions/': { results: [ENDPOINT] },
        },
        post: {
            '/api/projects/:team_id/endpoints/:name/materialization_suggestion/': suggestion,
        },
    })
    const { loadEndpoint } = useActions(endpointLogic)
    const { endpoint } = useValues(endpointLogic)
    const { openMaterializationSuggestionModal } = useActions(endpointSceneLogic)

    useEffect(() => {
        loadEndpoint(ENDPOINT.name)
    }, [loadEndpoint])

    useEffect(() => {
        if (openModal && endpoint) {
            openMaterializationSuggestionModal()
        }
    }, [openModal, endpoint, openMaterializationSuggestionModal])

    return <EndpointConfiguration />
}

export const OptimizeWithAIButton: StoryFn<StoryProps> = Template.bind({})
OptimizeWithAIButton.args = { suggestion: suggestionOk, openModal: false }
OptimizeWithAIButton.parameters = {
    testOptions: { waitForSelector: '[data-attr="endpoint-optimize-with-ai"]' },
}

export const SuggestionReady: StoryFn<StoryProps> = Template.bind({})
SuggestionReady.args = { suggestion: suggestionOk, openModal: true }
SuggestionReady.parameters = { testOptions: { waitForSelector: '.LemonModal .CodeSnippet' } }

export const SuggestionCannotFix: StoryFn<StoryProps> = Template.bind({})
SuggestionCannotFix.args = { suggestion: suggestionCannotFix, openModal: true }
SuggestionCannotFix.parameters = { testOptions: { waitForSelector: '.LemonModal .LemonBanner' } }

export const SuggestionFailedValidation: StoryFn<StoryProps> = Template.bind({})
SuggestionFailedValidation.args = { suggestion: suggestionFailed, openModal: true }
SuggestionFailedValidation.parameters = { testOptions: { waitForSelector: '.LemonModal .CodeSnippet' } }
