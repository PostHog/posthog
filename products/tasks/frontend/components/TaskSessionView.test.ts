import { LogEntry } from '../lib/parse-logs'
import { filterDuplicateInitialPromptEntry, mergeDuplicateUserPromptEntries } from './TaskSessionView'

const createEntry = (overrides: Partial<LogEntry>): LogEntry => ({
    id: 'entry-1',
    type: 'user',
    message: 'Hello from the initial prompt',
    ...overrides,
})

describe('filterDuplicateInitialPromptEntry', () => {
    it.each([
        {
            name: 'drops matching plain first entry',
            entries: [
                createEntry({ id: 'entry-1' }),
                createEntry({ id: 'entry-2', type: 'agent', message: 'I read the file' }),
            ],
            prompt: 'Hello from the initial prompt',
            expected: (entries: LogEntry[]) => [entries[1]],
        },
        {
            name: 'keeps first entry when message differs',
            entries: [
                createEntry({ id: 'entry-1', message: 'A different prompt' }),
                createEntry({ id: 'entry-2', type: 'agent', message: 'I read the file' }),
            ],
            prompt: 'Hello from the initial prompt',
            expected: (entries: LogEntry[]) => entries,
        },
        {
            name: 'keeps first entry when non-user leads',
            entries: [
                createEntry({ id: 'entry-1', type: 'system', message: 'Run started' }),
                createEntry({ id: 'entry-2' }),
            ],
            prompt: 'Hello from the initial prompt',
            expected: (entries: LogEntry[]) => entries,
        },
        {
            name: 'keeps matching first entry when it has attachments',
            entries: [
                createEntry({
                    id: 'entry-1',
                    attachments: [{ id: 'attachment-1', label: 'file.pdf' }],
                }),
                createEntry({ id: 'entry-2', type: 'agent', message: 'ok' }),
            ],
            prompt: 'Hello from the initial prompt',
            expected: (entries: LogEntry[]) => entries,
        },
    ])('$name', ({ entries, prompt, expected }) => {
        expect(filterDuplicateInitialPromptEntry(entries, prompt)).toEqual(expected(entries))
    })
})

describe('mergeDuplicateUserPromptEntries', () => {
    it.each([
        {
            name: 'keeps the attachment-bearing first entry when followed by plain duplicate text',
            entries: [
                createEntry({
                    id: 'entry-1',
                    message: 'Please inspect the attached file',
                    attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
                }),
                createEntry({ id: 'entry-2', message: 'Please inspect the attached file' }),
            ],
            expected: [
                createEntry({
                    id: 'entry-1',
                    message: 'Please inspect the attached file',
                    attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
                }),
            ],
        },
        {
            name: 'replaces a plain user entry with a later attachment-bearing duplicate',
            entries: [
                createEntry({ id: 'entry-1', message: 'Please inspect the attached file' }),
                createEntry({
                    id: 'entry-2',
                    message: 'Please inspect the attached file',
                    attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
                }),
            ],
            expected: [
                createEntry({
                    id: 'entry-2',
                    message: 'Please inspect the attached file',
                    attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
                }),
            ],
        },
        {
            name: 'merges attachments when both duplicate entries have them',
            entries: [
                createEntry({
                    id: 'entry-1',
                    message: 'Please inspect the attached file',
                    attachments: [{ id: 'attachment-1', label: 'Receipt-2264-0277.pdf' }],
                }),
                createEntry({
                    id: 'entry-2',
                    message: 'Please inspect the attached file',
                    attachments: [{ id: 'attachment-2', label: 'New Project.png' }],
                }),
            ],
            expected: [
                createEntry({
                    id: 'entry-1',
                    message: 'Please inspect the attached file',
                    attachments: [
                        { id: 'attachment-1', label: 'Receipt-2264-0277.pdf' },
                        { id: 'attachment-2', label: 'New Project.png' },
                    ],
                }),
            ],
        },
        {
            name: 'keeps distinct user entries untouched',
            entries: [
                createEntry({ id: 'entry-1', message: 'First prompt' }),
                createEntry({ id: 'entry-2', message: 'Second prompt' }),
            ],
            expected: [
                createEntry({ id: 'entry-1', message: 'First prompt' }),
                createEntry({ id: 'entry-2', message: 'Second prompt' }),
            ],
        },
    ])('$name', ({ entries, expected }) => {
        expect(mergeDuplicateUserPromptEntries(entries)).toEqual(expected)
    })
})
