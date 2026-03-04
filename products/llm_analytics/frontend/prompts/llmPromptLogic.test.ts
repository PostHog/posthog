import { expectLogic } from 'kea-test-utils'

import { NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { PromptAnalyticsScope, PromptMode, llmPromptLogic } from './llmPromptLogic'

const mockPrompt = {
    id: 'prompt-version-2',
    name: 'my-test-prompt',
    prompt: 'You are a helpful assistant.',
    version: 2,
    latest_version: 2,
    version_count: 2,
    first_version_created_at: '2024-01-01T00:00:00Z',
    is_latest: true,
    deleted: false,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
    created_by: { id: 1, email: 'test@example.com' },
    versions: [
        {
            id: 'prompt-version-2',
            version: 2,
            created_by: { id: 1, email: 'test@example.com' },
            created_at: '2024-01-02T00:00:00Z',
            is_latest: true,
        },
        {
            id: 'prompt-version-1',
            version: 1,
            created_by: { id: 1, email: 'test@example.com' },
            created_at: '2024-01-01T00:00:00Z',
            is_latest: false,
        },
    ],
    has_more: false,
}

describe('llmPromptLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('defaults to view mode for existing prompts', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            mode: PromptMode.View,
            analyticsScope: PromptAnalyticsScope.Selected,
        })

        logic.unmount()
    })

    it('builds related traces query for the selected version by default', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        const query = logic.values.relatedTracesQuery
        expect(query).not.toBeNull()
        expect(query?.kind).toBe(NodeKind.DataTableNode)

        const source = query?.source as TracesQuery
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_version_id',
                value: 'prompt-version-2',
                operator: PropertyOperator.Exact,
            },
        ])
        expect(source.dateRange?.date_from).toBe('-7d')

        logic.unmount()
    })

    it('switches traces and usage filters to all current versions scope', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)
        logic.actions.setAnalyticsScope(PromptAnalyticsScope.AllVersions)

        await expectLogic(logic).toMatchValues({
            analyticsScope: PromptAnalyticsScope.AllVersions,
            promptUsagePropertyFilter: [
                {
                    key: 'prompt_name',
                    type: PropertyFilterType.Event,
                    value: 'my-test-prompt',
                    operator: PropertyOperator.Exact,
                },
            ],
        })

        const query = logic.values.relatedTracesQuery
        const source = query?.source as TracesQuery
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            },
        ])
        expect(source.dateRange?.date_from).toBe('2024-01-01T00:00:00Z')

        logic.unmount()
    })

    it('builds a view-all-traces URL using the selected version filter', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        const url = logic.values.viewAllTracesUrl
        expect(url).toContain('/llm-analytics/traces?')

        const filterParam = url.split('filters=')[1]
        const decodedFilter = JSON.parse(decodeURIComponent(filterParam))
        expect(decodedFilter).toEqual([
            {
                type: PropertyFilterType.Event,
                key: '$ai_prompt_version_id',
                value: 'prompt-version-2',
                operator: PropertyOperator.Exact,
            },
        ])

        logic.unmount()
    })

    it('includes the selected version in breadcrumbs', async () => {
        const logic = llmPromptLogic({ promptName: 'existing-prompt' })
        logic.mount()
        logic.actions.setPrompt(mockPrompt)

        expect(logic.values.breadcrumbs[1].name).toBe('my-test-prompt v2')

        logic.unmount()
    })
})
