import { type DraftStorage, DraftStore } from './draftStore'

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
})
