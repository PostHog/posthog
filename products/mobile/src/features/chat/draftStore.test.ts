import * as Crypto from 'expo-crypto'

import { type DraftStorage, DraftStorageLimitError, DraftStore } from './draftStore'
import { EMPTY_QUEUE, queueActions, queueReducer } from './messageQueue'

function memoryStorage(): DraftStorage {
    const values = new Map<string, string>()
    return {
        getItem: async (key) => values.get(key) ?? null,
        setItem: async (key, value) => {
            values.set(key, value)
        },
        removeItem: async (key) => {
            values.delete(key)
        },
    }
}

const draft = (text: string, reportIds: string[] = []): { text: string; reportIds: string[] } => ({ text, reportIds })

let nextQueueId = 0
jest.spyOn(Crypto, 'randomUUID').mockImplementation(
    () => `00000000-0000-4000-8000-${String(++nextQueueId).padStart(12, '0')}`
)

describe('chat draft persistence', () => {
    it('restores across app restarts and isolates account, host and project scopes', async () => {
        const storage = memoryStorage()
        const store = new DraftStore(storage)
        await store.save('us-account1-project1', 'task:1', draft('  Keep spacing  ', ['report-1']))
        const restarted = new DraftStore(storage)
        expect(await restarted.load('us-account1-project1', 'task:1')).toEqual(draft('  Keep spacing  ', ['report-1']))
        for (const scope of ['eu-account1-project1', 'us-account2-project1', 'us-account1-project2']) {
            expect(await restarted.load(scope, 'task:1')).toBeNull()
        }
    })

    it('bounds storage at 50 recently saved drafts and removes emptied entries', async () => {
        const store = new DraftStore(memoryStorage())
        for (let index = 0; index < 51; index++) {
            await store.save('project', `task:${index}`, draft(`message ${index}`))
        }
        expect(await store.load('project', 'task:0')).toBeNull()
        expect(await store.load('project', 'task:1')).toEqual(draft('message 1'))
        await store.save('project', 'task:1', draft(' \n '))
        expect(await store.load('project', 'task:1')).toBeNull()
    })

    it.each([true, false])('preserves a later draft when a pending send settles with sent=%s', async (sent) => {
        const store = new DraftStore(memoryStorage())
        const settle = await store.beginSend('project', 'task:1', draft('First', ['report-1']))
        expect(await store.load('project', 'task:1')).toBeNull()
        await store.save('project', 'task:1', draft('Follow up', ['report-2']))
        await settle(sent)
        expect(await store.load('project', 'task:1')).toEqual(draft('Follow up', ['report-2']))
    })

    it('recovers a send interrupted by restart and clears an accepted send', async () => {
        const storage = memoryStorage()
        const store = new DraftStore(storage)
        await store.beginSend('project', 'task:1', draft('Interrupted'))
        const restarted = new DraftStore(storage)
        expect(await restarted.load('project', 'task:1')).toEqual(draft('Interrupted'))
        const settle = await restarted.beginSend('project', 'task:1', draft('Interrupted'))
        await settle(true)
        expect(await restarted.load('project', 'task:1')).toBeNull()
    })

    it.each(['read', 'write'])(
        'clears a stale accepted-send marker on autosave after a failed settlement %s',
        async (failure) => {
            const storage = memoryStorage()
            const store = new DraftStore(storage)
            const queued = queueReducer(EMPTY_QUEUE, queueActions.enqueue('Queued follow-up'))
            await store.saveQueue('project', 'task:1', queued)
            const settle = await store.beginSend('project', 'task:1', draft('Accepted'))
            if (failure === 'read') {
                jest.spyOn(storage, 'getItem').mockRejectedValueOnce(new Error('Read failed'))
            } else {
                jest.spyOn(storage, 'setItem').mockRejectedValueOnce(new Error('Write failed'))
            }
            await expect(settle(true)).rejects.toThrow()
            await store.save('project', 'task:1', draft('New typing'))
            await store.save('project', 'task:1', draft(''))
            const restarted = new DraftStore(storage)
            expect(await restarted.load('project', 'task:1')).toBeNull()
            expect((await restarted.loadQueue('project', 'task:1')).rows[0]?.text).toBe('Queued follow-up')
        }
    )

    it('moves pending sends to the created task without redirecting the next new chat', async () => {
        const store = new DraftStore(memoryStorage())
        const settle = await store.beginSend('project', 'new-chat', draft('First'))
        await store.move('project', 'new-chat', 'task:1')
        await store.save('project', 'new-chat', draft('Second'))
        await settle(false)
        expect(await store.load('project', 'task:1')).toEqual(draft('First'))
        expect(await store.load('project', 'new-chat')).toEqual(draft('Second'))
    })

    it('sign-out invalidates pending callbacks and queued saves', async () => {
        const store = new DraftStore(memoryStorage())
        const settle = await store.beginSend('project', 'task:1', draft('Private'))
        const save = store.save('project', 'task:2', draft('Queued'))
        await store.clear(['project'])
        await save
        await settle(false)
        expect(await store.load('project', 'task:1')).toBeNull()
        expect(await store.load('project', 'task:2')).toBeNull()
    })

    it.each(['{', '[]', '{"task:1":{"draft":{"text":7,"reportIds":[null]}}}'])(
        'ignores corrupt storage %s',
        async (raw) => {
            const storage = memoryStorage()
            await storage.setItem('project', raw)
            const store = new DraftStore(storage)
            expect(await store.load('project', 'task:1')).toBeNull()
            await store.save('project', 'task:2', draft('Still usable'))
            expect(await store.load('project', 'task:2')).toEqual(draft('Still usable'))
        }
    )
    it.each(['queued', 'sending'])(
        'recovers %s rows held across restart without persisting file paths',
        async (stage) => {
            const storage = memoryStorage()
            const store = new DraftStore(storage)
            let queue = queueReducer(
                EMPTY_QUEUE,
                queueActions.enqueue('Question', [
                    {
                        id: 'file-1',
                        uri: 'file:///private/example',
                        name: 'example.txt',
                        size: 1,
                        contentType: 'text/plain',
                        isImage: false,
                    },
                ])
            )
            if (stage === 'sending') queue = queueReducer(queue, queueActions.hold('unconfirmed'))
            await store.saveQueue('project', 'task:1', queue, draft(''))
            await store.save('project', 'task:1', draft('Next question'))
            const restarted = new DraftStore(storage)
            expect(await restarted.load('project', 'task:1')).toEqual(draft('Next question'))
            expect(await restarted.loadQueue('project', 'task:1')).toEqual({
                rows: [{ id: queue.rows[0]?.id, text: 'Question', attachments: [], missingAttachments: 1 }],
                hold: 'unconfirmed',
            })
            expect(await storage.getItem('project')).not.toContain('file:///')
            for (const scope of ['other-account', 'other-host', 'other-project']) {
                expect((await restarted.loadQueue(scope, 'task:1')).rows).toEqual([])
            }
            expect((await restarted.loadQueue('project', 'task:2')).rows).toEqual([])
            await restarted.clear(['project'])
            expect((await new DraftStore(storage).loadQueue('project', 'task:1')).rows).toEqual([])
        }
    )

    it('retains an in-flight batch until acknowledgment and removes only that batch', async () => {
        const storage = memoryStorage()
        const store = new DraftStore(storage)
        const first = queueReducer(EMPTY_QUEUE, queueActions.enqueue('First'))
        await store.saveQueue('project', 'new-chat', first, draft(''))
        await store.move('project', 'new-chat', 'task:1')
        expect((await store.loadQueue('project', 'new-chat')).rows).toEqual([])
        const held = queueReducer(first, queueActions.hold('unconfirmed'))
        await store.saveQueue('project', 'task:1', held)
        const later = queueReducer(held, queueActions.enqueue('Second'))
        await store.saveQueue('project', 'task:1', later)
        const confirmed = queueReducer(later, { type: 'delivered', ids: first.rows.map((row) => row.id) })
        await store.saveQueue('project', 'task:1', confirmed)
        expect((await new DraftStore(storage).loadQueue('project', 'task:1')).rows.map((row) => row.text)).toEqual([
            'Second',
        ])
    })
    it('clears an in-flight queue write on sign-out and refuses saves queued before it', async () => {
        const storage = memoryStorage()
        let finish!: () => void
        const gate = new Promise<void>((resolve) => {
            finish = resolve
        })
        const write = storage.setItem
        storage.setItem = async (key, value) => {
            await gate
            await write(key, value)
        }
        const store = new DraftStore(storage)
        const queue = queueReducer(EMPTY_QUEUE, queueActions.enqueue('Private text'))
        const saving = store.saveQueue('project', 'task:1', queue)
        const waiting = store.saveQueue('project', 'task:2', queue).catch(() => undefined)
        const cleared = store.clear(['project'])
        finish()
        await Promise.all([saving.catch(() => undefined), waiting, cleared])
        const restarted = new DraftStore(storage)
        expect((await restarted.loadQueue('project', 'task:1')).rows).toEqual([])
        expect((await restarted.loadQueue('project', 'task:2')).rows).toEqual([])
    })
    it('refuses additional queued text before it can make saved queues unreadable', async () => {
        const storage = memoryStorage()
        const store = new DraftStore(storage)
        const first = queueReducer(EMPTY_QUEUE, queueActions.enqueue('First question'))
        await store.saveQueue('project', 'task:1', first)
        const before = await storage.getItem('project')
        const oversized = queueReducer(EMPTY_QUEUE, queueActions.enqueue('x'.repeat(128 * 1024)))
        await expect(store.saveQueue('project', 'task:2', oversized, draft(''))).rejects.toBeInstanceOf(
            DraftStorageLimitError
        )
        expect(await storage.getItem('project')).toBe(before)
        expect((await new DraftStore(storage).loadQueue('project', 'task:1')).rows[0]?.text).toBe('First question')
        await store.saveQueue('project', 'task:2', first)
        expect((await store.loadQueue('project', 'task:2')).rows).toHaveLength(1)
    })
    it('allows shrinking a preexisting oversized project without dropping remaining queues', async () => {
        const storage = memoryStorage()
        const rows = Object.fromEntries(
            ['one', 'two', 'three'].map((id) => [
                `task:${id}`,
                { draft: draft(''), queue: { rows: [{ id, text: 'x'.repeat(80_000), attachments: [] }], hold: null } },
            ])
        )
        await storage.setItem('project', JSON.stringify(rows))
        const store = new DraftStore(storage)
        await store.saveQueue('project', 'task:one', EMPTY_QUEUE)
        expect((await storage.getItem('project'))?.length).toBeGreaterThan(128 * 1024)
        expect((await store.loadQueue('project', 'task:two')).rows[0]?.text).toHaveLength(80_000)
        await store.saveQueue('project', 'task:two', EMPTY_QUEUE)
        expect((await store.loadQueue('project', 'task:three')).rows[0]?.text).toHaveLength(80_000)
    })

    it('does not retain a pending-send handle when its durable write exceeds the budget', async () => {
        const store = new DraftStore(memoryStorage())
        const queue = queueReducer(EMPTY_QUEUE, queueActions.enqueue('x'.repeat(100_000)))
        await store.saveQueue('project', 'task:queued', queue)
        await expect(store.beginSend('project', 'new-chat', draft('y'.repeat(40_000)))).rejects.toBeInstanceOf(
            DraftStorageLimitError
        )
        await store.save('project', 'new-chat', draft('Later'))
        expect(await store.load('project', 'new-chat')).toEqual(draft('Later'))
        const settle = await store.beginSend('project', 'new-chat', draft('Next'))
        await settle(true)
        expect(await store.load('project', 'new-chat')).toBeNull()
        expect((await store.loadQueue('project', 'task:queued')).rows[0]?.text).toHaveLength(100_000)
    })
    it('adopts an unchanged near-limit queue even when the task key is longer', async () => {
        const storage = memoryStorage()
        const store = new DraftStore(storage)
        const queued = queueReducer(EMPTY_QUEUE, queueActions.enqueue('Question'))
        await store.saveQueue('project', 'new-chat', queued)
        const overhead = (await storage.getItem('project'))?.length ?? 0
        const text = 'x'.repeat(128 * 1024 - overhead + 'Question'.length)
        const full = queueReducer(EMPTY_QUEUE, queueActions.enqueue(text))
        await store.saveQueue('project', 'new-chat', full)
        const task = 'task:00000000-0000-4000-8000-000000000001'
        await store.move('project', 'new-chat', task)
        expect((await store.loadQueue('project', 'new-chat')).rows).toEqual([])
        expect((await store.loadQueue('project', task)).rows[0]?.text).toBe(text)
        const larger = queueReducer(full, queueActions.enqueue('Additional text'))
        await expect(store.saveQueue('project', task, larger)).rejects.toBeInstanceOf(DraftStorageLimitError)
        expect((await store.loadQueue('project', task)).rows).toHaveLength(1)
    })
})
