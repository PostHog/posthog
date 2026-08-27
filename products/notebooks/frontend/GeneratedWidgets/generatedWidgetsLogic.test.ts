import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { notebookWidgetsList } from 'products/notebooks/frontend/generated/api'
import type { WidgetCatalogApi } from 'products/notebooks/frontend/generated/api.schemas'

import { generatedWidgetsLogic } from './generatedWidgetsLogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebookWidgetsList: jest.fn(),
}))

const widget = (id: string, name: string): WidgetCatalogApi => ({
    id,
    name,
    title: name,
    prompt_preview: '',
    description: '',
    visibility: 'team',
    notebook_short_id: null,
    notebook_node_id: null,
    current_version_id: '00000000-0000-0000-0000-000000000001',
    version_count: 1,
    usage_count: 1,
    created_by: null,
    created_at: '2026-08-27T12:00:00Z',
    updated_at: '2026-08-27T12:00:00Z',
})

describe('generatedWidgetsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebookWidgetsList).mockReset()
    })

    afterEach(() => {
        generatedWidgetsLogic.unmount()
    })

    it('clears the previous project catalog before loading the next project', async () => {
        const previousWidget = widget('00000000-0000-0000-0000-000000000002', 'Previous project widget')
        const nextWidget = widget('00000000-0000-0000-0000-000000000003', 'Next project widget')
        let resolveNextProject: (page: Awaited<ReturnType<typeof notebookWidgetsList>>) => void = () => undefined
        jest.mocked(notebookWidgetsList)
            .mockResolvedValueOnce({ results: [previousWidget], count: 1, next: null, previous: null })
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveNextProject = resolve
                    })
            )

        generatedWidgetsLogic.mount()
        await expectLogic(generatedWidgetsLogic).toFinishAllListeners()
        expect(generatedWidgetsLogic.values.widgets).toEqual([previousWidget])

        const nextTeam = { ...teamLogic.values.currentTeam!, id: MOCK_TEAM_ID + 1 }
        teamLogic.actions.loadCurrentTeamSuccess(nextTeam)
        await expectLogic(generatedWidgetsLogic).toDispatchActions(['loadWidgets'])
        expect(generatedWidgetsLogic.values.widgets).toEqual([])

        resolveNextProject({ results: [nextWidget], count: 1, next: null, previous: null })
        await expectLogic(generatedWidgetsLogic).toFinishAllListeners()

        expect(notebookWidgetsList).toHaveBeenLastCalledWith(String(nextTeam.id), {
            limit: 50,
            offset: 0,
            search: undefined,
        })
        expect(generatedWidgetsLogic.values.widgets).toEqual([nextWidget])
    })
})
