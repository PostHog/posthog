import { runInNewContext } from 'node:vm'

import { blockChunkScript, blockStatusScript, cancelBlocksScript } from './playerHtml'
import { ReplayBlockBridge, replayWindowAt } from './playerRuntime'

describe('embedded replay runtime', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
    })

    function bridge(): {
        blocks: ReplayBlockBridge
        post: jest.Mock
        inject: (script: string) => void
    } {
        const post = jest.fn()
        const blocks = new ReplayBlockBridge(post, 100)
        const context = {
            window: {
                __receiveReplayBlock: (id: number, text: string, done: boolean) => blocks.receive(id, text, done),
                __setReplayBlockLoading: (id: number, loading: boolean) => blocks.setLoading(id, loading),
                __cancelReplayBlocks: () => blocks.cancel(),
            },
        }
        return { blocks, post, inject: (script) => void runInNewContext(script, context) }
    }

    test('keeps receiving native chunks while they arrive before the inactivity timeout and ignores late delivery', async () => {
        const { blocks, post, inject } = bridge()
        const response = blocks.request('/__blocks/2')
        expect(post).toHaveBeenCalledWith({ type: 'block', id: 1, index: 2 })
        jest.advanceTimersByTime(99)
        inject(blockChunkScript(1, '{"example":', false))
        jest.advanceTimersByTime(99)
        inject(blockChunkScript(1, 'true}', true))
        inject(blockChunkScript(1, 'late content', true))
        expect(await (await response).text()).toBe('{"example":true}')
        expect(jest.getTimerCount()).toBe(0)
    })

    test.each([false, true])('rejects a stalled request after native acknowledgement=%s', async (acknowledged) => {
        const { blocks, inject } = bridge()
        const response = blocks.request('/__blocks/0')
        const settled = jest.fn()
        void response.then(settled, settled)
        const rejected = expect(response).rejects.toThrow('timed out')
        inject(blockChunkScript(1, 'partial content', false))
        if (acknowledged) {
            inject(blockStatusScript(1, false))
            jest.advanceTimersByTime(200)
            await Promise.resolve()
            expect(settled).not.toHaveBeenCalled()
            expect(jest.getTimerCount()).toBe(0)
            inject(blockStatusScript(1, true))
        }
        jest.advanceTimersByTime(100)
        await rejected
        inject(blockChunkScript(1, 'late content', true))
        expect(jest.getTimerCount()).toBe(0)
    })

    test('native cancellation rejects queued and loading blocks and prevents subsequent loads', async () => {
        const { blocks, post, inject } = bridge()
        const rejected = [
            expect(blocks.request('/__blocks/0')).rejects.toThrow('cancelled'),
            expect(blocks.request('/__blocks/1')).rejects.toThrow('cancelled'),
        ]
        inject(blockStatusScript(1, false))
        inject(blockChunkScript(2, 'partial content', false))
        inject(cancelBlocksScript())
        await Promise.all(rejected)
        await expect(blocks.request('/__blocks/2')).rejects.toThrow('cancelled')
        inject(blockChunkScript(2, 'late content', true))
        inject(blockStatusScript(1, true))
        expect(jest.getTimerCount()).toBe(0)
        expect(post).toHaveBeenCalledTimes(2)
    })

    test.each([
        [4000, false, 1],
        [6000, false, 2],
        [5000, true, 2],
    ])('selects the owner at %s with an active boundary=%s', (timestamp, activeBoundary, expected) => {
        const windows = [
            { windowId: 1, firstTimestamp: 1000, lastTimestamp: 5000 },
            { windowId: 2, firstTimestamp: 3000, lastTimestamp: 9000 },
        ]
        const segments = [{ windowId: 1, startTimestamp: 1000, endTimestamp: 9000, isActive: false }]
        if (activeBoundary) {
            segments.push({ windowId: 2, startTimestamp: 5000, endTimestamp: 9000, isActive: true })
        }
        expect(replayWindowAt(windows, segments, timestamp)).toBe(windows[expected - 1])
    })
})
