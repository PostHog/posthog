import { expectLogic } from 'kea-test-utils'

import { NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { PromptMode, llmPromptLogic } from './llmPromptLogic'

describe('llmPromptLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('PromptMode enum', () => {
        it('has correct enum values', () => {
            expect(PromptMode.View).toBe('view')
            expect(PromptMode.Edit).toBe('edit')
        })
    })

    describe('mode handling', () => {
        it('defaults to View mode for existing prompts', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                mode: PromptMode.View,
            })

            logic.unmount()
        })

        it('respects mode from props', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123', mode: PromptMode.Edit })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                mode: PromptMode.Edit,
            })

            logic.unmount()
        })

        it('switches mode via setMode action', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                mode: PromptMode.View,
            })

            logic.actions.setMode(PromptMode.Edit)

            await expectLogic(logic).toMatchValues({
                mode: PromptMode.Edit,
            })

            logic.actions.setMode(PromptMode.View)

            await expectLogic(logic).toMatchValues({
                mode: PromptMode.View,
            })

            logic.unmount()
        })
    })

    describe('isViewMode selector', () => {
        it('returns true for existing prompts in View mode', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                isViewMode: true,
            })

            logic.unmount()
        })

        it('returns false for existing prompts in Edit mode', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123', mode: PromptMode.Edit })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                isViewMode: false,
            })

            logic.unmount()
        })

        it('returns false for new prompts regardless of mode', async () => {
            const logic = llmPromptLogic({ promptName: 'new' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                isViewMode: false,
            })

            logic.unmount()
        })
    })

    describe('isEditMode selector', () => {
        it('returns true for new prompts', async () => {
            const logic = llmPromptLogic({ promptName: 'new' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                isEditMode: true,
            })

            logic.unmount()
        })

        it('returns true for existing prompts in Edit mode', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123', mode: PromptMode.Edit })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                isEditMode: true,
            })

            logic.unmount()
        })

        it('returns false for existing prompts in View mode', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                isEditMode: false,
            })

            logic.unmount()
        })
    })

    describe('relatedTracesQuery selector', () => {
        it('returns null when no prompt is loaded', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                relatedTracesQuery: null,
            })

            logic.unmount()
        })

        it('returns null for form values without id', async () => {
            const logic = llmPromptLogic({ promptName: 'new' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                relatedTracesQuery: null,
            })

            logic.unmount()
        })

        it('builds correct query when prompt is loaded', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            const mockPrompt = {
                id: 'existing-prompt-123',
                name: 'my-test-prompt',
                prompt: 'You are a helpful assistant.',
                team_id: 1,
                created_at: '2024-01-01T00:00:00Z',
                created_by: { id: 1, email: 'test@example.com' },
            }

            logic.actions.setPrompt(mockPrompt)
            await expectLogic(logic).toFinishAllListeners()

            const query = logic.values.relatedTracesQuery
            expect(query).not.toBeNull()
            expect(query!.kind).toBe(NodeKind.DataTableNode)

            const source = query!.source as TracesQuery
            expect(source.kind).toBe(NodeKind.TracesQuery)
            expect(source.dateRange).toEqual({
                date_from: '-7d',
                date_to: undefined,
            })
            expect(source.filterTestAccounts).toBe(false)
            expect(source.filterSupportTraces).toBe(true)
            expect(source.properties).toHaveLength(1)
            expect(source.properties![0]).toEqual({
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            })

            expect(query!.columns).toEqual([
                'id',
                'traceName',
                'person',
                'errors',
                'totalLatency',
                'usage',
                'totalCost',
                'timestamp',
            ])
            expect(query!.showDateRange).toBe(true)
            expect(query!.showReload).toBe(true)
            expect(query!.showSearch).toBe(false)
            expect(query!.showTestAccountFilters).toBe(true)
            expect(query!.showExport).toBe(false)

            logic.unmount()
        })
    })

    describe('viewAllTracesUrl selector', () => {
        it('returns base traces URL when no prompt is loaded', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            expect(logic.values.viewAllTracesUrl).toBe('/llm-analytics/traces')

            logic.unmount()
        })

        it('returns base traces URL for form values without id', async () => {
            const logic = llmPromptLogic({ promptName: 'new' })
            logic.mount()

            expect(logic.values.viewAllTracesUrl).toBe('/llm-analytics/traces')

            logic.unmount()
        })

        it('builds URL with encoded filter when prompt is loaded', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            const mockPrompt = {
                id: 'existing-prompt-123',
                name: 'my-test-prompt',
                prompt: 'You are a helpful assistant.',
                team_id: 1,
                created_at: '2024-01-01T00:00:00Z',
                created_by: { id: 1, email: 'test@example.com' },
            }

            logic.actions.setPrompt(mockPrompt)
            await expectLogic(logic).toFinishAllListeners()

            const url = logic.values.viewAllTracesUrl
            expect(url).toContain('/llm-analytics/traces?filters=')

            const filterParam = url.split('filters=')[1]
            const decodedFilter = JSON.parse(decodeURIComponent(filterParam))

            expect(decodedFilter).toHaveLength(1)
            expect(decodedFilter[0]).toEqual({
                type: PropertyFilterType.Event,
                key: '$ai_prompt_name',
                value: 'my-test-prompt',
                operator: PropertyOperator.Exact,
            })

            logic.unmount()
        })

        it('encodes special characters in prompt name', async () => {
            const logic = llmPromptLogic({ promptName: 'existing-prompt-123' })
            logic.mount()

            const mockPrompt = {
                id: 'existing-prompt-123',
                name: 'prompt-with-special-chars_123',
                prompt: 'Test prompt',
                team_id: 1,
                created_at: '2024-01-01T00:00:00Z',
                created_by: { id: 1, email: 'test@example.com' },
            }

            logic.actions.setPrompt(mockPrompt)
            await expectLogic(logic).toFinishAllListeners()

            const url = logic.values.viewAllTracesUrl

            const filterParam = url.split('filters=')[1]
            const decodedFilter = JSON.parse(decodeURIComponent(filterParam))

            expect(decodedFilter[0].value).toBe('prompt-with-special-chars_123')

            logic.unmount()
        })
    })
})
