import { LogEntry } from '../lib/parse-logs'
import { filterDuplicateInitialPromptEntry, mergeDuplicateUserPromptEntries } from './TaskSessionView'

describe('filterDuplicateInitialPromptEntry', () => {
    const createEntry = (overrides: Partial<LogEntry>): LogEntry => ({
        id: 'entry-1',
        type: 'user',
        message: 'Hello from the initial prompt',
        ...overrides,
    })

    it('drops the first user entry when it matches the initial prompt', () => {
        const entries = [
            createEntry({ id: 'entry-1' }),
            createEntry({ id: 'entry-2', type: 'agent', message: 'I read the file' }),
        ]

        expect(filterDuplicateInitialPromptEntry(entries, 'Hello from the initial prompt')).toEqual([entries[1]])
    })

    it('keeps the first user entry when it does not match the initial prompt', () => {
        const entries = [
            createEntry({ id: 'entry-1', message: 'A different prompt' }),
            createEntry({ id: 'entry-2', type: 'agent', message: 'I read the file' }),
        ]

        expect(filterDuplicateInitialPromptEntry(entries, 'Hello from the initial prompt')).toEqual(entries)
    })

    it('keeps non-user leading entries even when the prompt text matches later', () => {
        const entries = [
            createEntry({ id: 'entry-1', type: 'system', message: 'Run started' }),
            createEntry({ id: 'entry-2' }),
        ]

        expect(filterDuplicateInitialPromptEntry(entries, 'Hello from the initial prompt')).toEqual(entries)
    })
})

describe('mergeDuplicateUserPromptEntries', () => {
    const createEntry = (overrides: Partial<LogEntry>): LogEntry => ({
        id: 'entry-1',
        type: 'user',
        message: 'Please inspect the attached file',
        ...overrides,
    })

    it('keeps the attachment-bearing user entry when the next entry duplicates its text', () => {
        const attachmentEntry = createEntry({
            id: 'entry-1',
            attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
        })
        const duplicateTextEntry = createEntry({ id: 'entry-2' })

        expect(mergeDuplicateUserPromptEntries([attachmentEntry, duplicateTextEntry])).toEqual([attachmentEntry])
    })

    it('replaces a plain user entry with a later attachment-bearing duplicate', () => {
        const plainEntry = createEntry({ id: 'entry-1' })
        const attachmentEntry = createEntry({
            id: 'entry-2',
            attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
        })

        expect(mergeDuplicateUserPromptEntries([plainEntry, attachmentEntry])).toEqual([attachmentEntry])
    })

    it('keeps distinct user entries untouched', () => {
        const firstEntry = createEntry({ id: 'entry-1', message: 'First prompt' })
        const secondEntry = createEntry({ id: 'entry-2', message: 'Second prompt' })

        expect(mergeDuplicateUserPromptEntries([firstEntry, secondEntry])).toEqual([firstEntry, secondEntry])
    })
})
