import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { mindmapLogic } from './mindmapLogic'

jest.mock('products/mindmap/frontend/generated/api', () => ({
    __esModule: true,
    mindmapStateRetrieve: jest.fn(),
    mindmapPostitsBulkPositionCreate: jest.fn(),
}))

const mockedApi = require('products/mindmap/frontend/generated/api')

function postit(short_id: string, position_x = 0, position_y = 0, extra: Record<string, unknown> = {}): any {
    return {
        short_id,
        title: short_id,
        body: '',
        color: 'yellow',
        emoji: '',
        position_x,
        position_y,
        notebook_short_id: null,
        ...extra,
    }
}

describe('mindmapLogic', () => {
    let logic: ReturnType<typeof mindmapLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        logic = mindmapLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loadState populates postits and edges', async () => {
        mockedApi.mindmapStateRetrieve.mockResolvedValueOnce({
            postits: [postit('a'), postit('b')],
            edges: [{ source: 'a', target: 'b' }],
            version: 'v1',
        })

        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()

        expect(logic.values.postits.map((p) => p.short_id)).toEqual(['a', 'b'])
        expect(logic.values.edges).toEqual([{ source: 'a', target: 'b' }])
        expect(logic.values.version).toEqual('v1')
    })

    it('subsequent loadState replaces postits and edges with the new server payload', async () => {
        mockedApi.mindmapStateRetrieve
            .mockResolvedValueOnce({
                postits: [postit('a', 0, 0), postit('b', 10, 10)],
                edges: [{ source: 'a', target: 'b' }],
                version: 'v1',
            })
            .mockResolvedValueOnce({
                postits: [postit('b', 20, 20), postit('c', 30, 30)],
                edges: [{ source: 'b', target: 'c' }],
                version: 'v2',
            })

        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()

        expect(logic.values.postits.map((p) => p.short_id)).toEqual(['b', 'c'])
        expect(logic.values.postits[0].position_x).toEqual(20)
        expect(logic.values.edges).toEqual([{ source: 'b', target: 'c' }])
        expect(logic.values.version).toEqual('v2')
    })

    it('sends If-None-Match on subsequent polls', async () => {
        mockedApi.mindmapStateRetrieve
            .mockResolvedValueOnce({ postits: [], edges: [], version: 'v1' })
            .mockResolvedValueOnce({ postits: [], edges: [], version: 'v1' })

        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()

        const firstCall = mockedApi.mindmapStateRetrieve.mock.calls[0]
        const secondCall = mockedApi.mindmapStateRetrieve.mock.calls[1]
        // First call: no If-None-Match header (no version yet).
        expect(firstCall[1]?.headers?.['If-None-Match']).toBeUndefined()
        // Second call: If-None-Match echoes the version received from the first.
        expect(secondCall[1].headers['If-None-Match']).toEqual('"v1"')
    })

    it('nodeDragged updates local position immediately and accumulates pendingDrags', async () => {
        mockedApi.mindmapStateRetrieve.mockResolvedValueOnce({
            postits: [postit('a', 10, 10)],
            edges: [],
            version: 'v1',
        })
        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()

        logic.actions.nodeDragged('a', 50, 75)

        expect(logic.values.pendingDrags).toEqual({ a: { position_x: 50, position_y: 75 } })
        expect(logic.values.postits[0].position_x).toEqual(50)
        expect(logic.values.postits[0].position_y).toEqual(75)
    })

    it('flushes pendingDrags via bulk_position after debounce', async () => {
        mockedApi.mindmapStateRetrieve.mockResolvedValueOnce({
            postits: [postit('a', 0, 0)],
            edges: [],
            version: 'v1',
        })
        mockedApi.mindmapPostitsBulkPositionCreate.mockResolvedValue({ updated: 1 })

        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()

        jest.useFakeTimers()
        try {
            logic.actions.nodeDragged('a', 30, 40)

            await expectLogic(logic, () => {
                jest.advanceTimersByTime(600)
            }).toDispatchActions(['flushPendingDrags', 'clearPendingDrags'])
        } finally {
            jest.useRealTimers()
        }

        expect(mockedApi.mindmapPostitsBulkPositionCreate).toHaveBeenCalledTimes(1)
        const callArgs = mockedApi.mindmapPostitsBulkPositionCreate.mock.calls[0]
        // Last positional argument carries the request body (regardless of how many leading args).
        const requestBody = callArgs[callArgs.length - 1]
        expect(requestBody).toEqual({
            updates: [{ short_id: 'a', position_x: 30, position_y: 40 }],
        })
        expect(logic.values.pendingDrags).toEqual({})
    })

    it('suppresses server position changes for nodes with pending drags', async () => {
        mockedApi.mindmapStateRetrieve
            .mockResolvedValueOnce({
                postits: [postit('a', 0, 0)],
                edges: [],
                version: 'v1',
            })
            .mockResolvedValueOnce({
                postits: [postit('a', 0, 0)],
                edges: [],
                version: 'v2',
            })

        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()
        logic.actions.nodeDragged('a', 100, 100)
        // A new server payload arrives while drag is still pending (debounce hasn't fired).
        await expectLogic(logic, () => logic.actions.loadState()).toFinishAllListeners()

        expect(logic.values.postits[0].position_x).toEqual(100)
        expect(logic.values.postits[0].position_y).toEqual(100)
    })
})
