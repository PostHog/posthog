import { TaskDraftPersistence, TaskDraftState, taskDraftStorageKey } from './taskDraftPersistence'

const key = taskDraftStorageKey('user-1', 997, 'task-1')
const empty: TaskDraftState = { runId: 'run-1', draft: '', queuedText: '', recovery: null }

describe('task draft persistence', () => {
    beforeEach(() => localStorage.clear())

    it('recovers an unconfirmed send before the queue and draft, then retains only newer text after acknowledgement', () => {
        const tab = new TaskDraftPersistence(key)
        tab.startDelivery('sent first')
        tab.save({ ...empty, queuedText: 'queued second', draft: 'unfinished third' })
        expect(new TaskDraftPersistence(key).restore()).toEqual({
            draft: 'sent first\n\nqueued second\n\nunfinished third',
            recovery: 'unconfirmed',
        })
        tab.finishDelivery({ ...empty, draft: 'unfinished third' })
        expect(new TaskDraftPersistence(key).restore()).toEqual({ draft: 'unfinished third', recovery: 'restored' })
        tab.save(empty)
        expect(new TaskDraftPersistence(key).restore()).toBeNull()
    })

    it('keeps the latest tab edit when an older send finishes or its unchanged page exits', () => {
        const olderTab = new TaskDraftPersistence(key)
        olderTab.startDelivery('sending')
        olderTab.save(empty)
        new TaskDraftPersistence(key).save({ ...empty, draft: 'newer tab edit' })
        olderTab.finishDelivery(empty)
        olderTab.save(empty)
        expect(new TaskDraftPersistence(key).restore()?.draft).toBe('newer tab edit')
        olderTab.save({ ...empty, draft: 'latest edit from the older tab' })
        expect(new TaskDraftPersistence(key).restore()?.draft).toBe('latest edit from the older tab')
    })

    it.each([
        ['user-2', 997, 'task-1'],
        ['user-1', 998, 'task-1'],
        ['user-1', 997, 'task-2'],
    ] as const)('does not restore another identity: %s/%s/%s', (userId, projectId, taskId) => {
        new TaskDraftPersistence(key).save({ ...empty, draft: 'private draft' })
        expect(new TaskDraftPersistence(taskDraftStorageKey(userId, projectId, taskId)).restore()).toBeNull()
    })

    it.each([
        'invalid json',
        JSON.stringify({ version: 0, draft: 'old format' }),
        JSON.stringify({ version: 1, draft: 123 }),
    ])('ignores malformed storage: %s', (value) => {
        localStorage.setItem(key, value)
        expect(new TaskDraftPersistence(key).restore()).toBeNull()
    })

    it('expires a draft after seven days', () => {
        new TaskDraftPersistence(key).save({ ...empty, draft: 'stale draft' })
        const now = jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 7 * 24 * 60 * 60 * 1000)
        try {
            expect(new TaskDraftPersistence(key).restore()).toBeNull()
            expect(localStorage.getItem(key)).toBeNull()
        } finally {
            now.mockRestore()
        }
    })

    it('tolerates disabled storage without preventing a send from finishing', () => {
        const storage = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new DOMException('Storage unavailable', 'QuotaExceededError')
        })
        try {
            const tab = new TaskDraftPersistence(key)
            expect(() => {
                tab.startDelivery('sending')
                tab.save(empty)
                tab.finishDelivery(empty)
            }).not.toThrow()
        } finally {
            storage.mockRestore()
        }
    })
})
