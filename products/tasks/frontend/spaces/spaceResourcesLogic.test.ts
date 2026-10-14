import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SpaceResourceConfigApi } from '../generated/api.schemas'
import { spaceResourcesLogic } from './spaceResourcesLogic'

describe('spaceResourcesLogic', () => {
    it('adds a file once during repeated activation and retains a featured canvas when pinning', async () => {
        initKeaTests()
        let saved: SpaceResourceConfigApi = { featured_canvas: 'canvas-a', resources: [] }
        const writes: SpaceResourceConfigApi[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/:id/resources/': () => [200, saved],
                '/api/projects/:team_id/file_system/': [200, { results: [], next: null, count: 0 }],
            },
            put: {
                '/api/projects/:team_id/task_channels/:id/resources/': async ({ request }) => {
                    saved = (await request.json()) as SpaceResourceConfigApi
                    writes.push(saved)
                    return [200, saved]
                },
            },
        })
        const logic = spaceResourcesLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.addFile('file-a')
        logic.actions.addFile('file-a')
        await expectLogic(logic).toFinishAllListeners()
        expect(writes).toEqual([{ featured_canvas: 'canvas-a', resources: [{ file_id: 'file-a', pinned: false }] }])
        logic.actions.togglePinned('file-a')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.config).toEqual({
            featured_canvas: 'canvas-a',
            resources: [{ file_id: 'file-a', pinned: true }],
        })
        logic.unmount()
    })
})
