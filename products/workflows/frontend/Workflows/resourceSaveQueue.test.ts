import type { ResourceEditedEvent } from '~/types'

import { ResourceSaveQueue } from './resourceSaveQueue'

const event = (overrides: Partial<ResourceEditedEvent> = {}): ResourceEditedEvent => ({
    notification_type: 'resource_edited',
    team_id: 1,
    resource_type: 'HogFlow',
    resource_id: 'flow-1',
    updated_at: '2026-09-25T10:00:05Z',
    actor_user_id: 2,
    ...overrides,
})

const queue = (loadedStamp: string | null = '2026-09-25T10:00:00Z', isBusy = false): ResourceSaveQueue =>
    new ResourceSaveQueue({
        resourceType: 'HogFlow',
        getResourceId: () => 'flow-1',
        getLoadedStamp: () => loadedStamp,
        isBusy: () => isBusy,
    })

describe('ResourceSaveQueue', () => {
    it('runs a save only after the one before it settles, even when that one fails', async () => {
        const saves = queue()
        const order: string[] = []
        let failFirst: (error: Error) => void = () => {}
        const first = saves.run(
            () =>
                new Promise((_, reject) => {
                    order.push('first started')
                    failFirst = reject
                })
        )
        const second = saves.run(async () => {
            order.push('second started')
            return 'saved'
        })
        await Promise.resolve()
        expect(order).toEqual(['first started'])
        expect(saves.inFlight).toBe(2)

        failFirst(new Error('409'))
        await expect(first).rejects.toThrow('409')
        await expect(second).resolves.toBe('saved')
        await saves.whenIdle()
        expect(order).toEqual(['first started', 'second started'])
        expect(saves.inFlight).toBe(0)
    })

    it.each([
        ['another resource type', 'ignore', event({ resource_type: 'HogFunction' })],
        ['another workflow', 'ignore', event({ resource_id: 'flow-2' })],
        ['the echo of our own save', 'ignore', event({ updated_at: '2026-09-25T10:00:00Z' })],
        ['an older copy', 'ignore', event({ updated_at: '2026-09-25T09:59:00Z' })],
        ['a newer copy from elsewhere', 'external', event()],
    ])('reads %s as %s', (_, verdict, incoming) => {
        expect(queue().classify(incoming)).toBe(verdict)
    })

    it('ignores every event until something has loaded', () => {
        expect(queue(null).classify(event())).toBe('ignore')
    })

    it('holds an event that lands mid-save and hands the latest one over once', async () => {
        const saves = queue()
        let finish: () => void = () => {}
        const saving = saves.run(() => new Promise<void>((resolve) => (finish = resolve)))

        expect(saves.classify(event({ updated_at: '2026-09-25T10:00:03Z' }))).toBe('defer')
        expect(saves.classify(event())).toBe('defer')
        await Promise.resolve()
        finish()
        await saving

        expect(saves.takeDeferred()).toEqual(event())
        expect(saves.takeDeferred()).toBeNull()
    })

    it('keeps holding a replayed event until the last queued save settles', async () => {
        const saves = queue()
        const finishers: (() => void)[] = []
        const first = saves.run(() => new Promise<void>((resolve) => finishers.push(resolve)))
        const second = saves.run(() => new Promise<void>((resolve) => finishers.push(resolve)))
        await Promise.resolve()

        expect(saves.classify(event())).toBe('defer')
        finishers[0]()
        await first
        const replayed = saves.takeDeferred()
        expect(replayed && saves.classify(replayed)).toBe('defer')

        await Promise.resolve()
        finishers[1]()
        await second
        const lastReplay = saves.takeDeferred()
        expect(lastReplay && saves.classify(lastReplay)).toBe('external')
    })

    it('holds events while the editor says it is busy', () => {
        expect(queue(undefined, true).classify(event())).toBe('defer')
    })
})
