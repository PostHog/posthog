import { LogEntry } from '../lib/parse-logs'
import { extractCurrentPlan } from './TaskPlanView'

const toolEntry = (overrides: Partial<LogEntry>): LogEntry => ({
    id: 'tool-1',
    type: 'tool',
    toolName: 'TodoWrite',
    toolStatus: 'completed',
    toolArgs: {},
    ...overrides,
})

describe('extractCurrentPlan', () => {
    it('returns null fields when there are no plan-related entries', () => {
        expect(extractCurrentPlan([])).toEqual({
            todos: null,
            todosTimestamp: undefined,
            planMarkdown: null,
            planTimestamp: undefined,
        })
    })

    it('extracts todos from the latest TodoWrite call', () => {
        const entries: LogEntry[] = [
            toolEntry({
                id: 'tool-1',
                timestamp: '2024-01-01T00:00:00Z',
                toolArgs: { todos: [{ content: 'first', status: 'pending' }] },
            }),
            toolEntry({
                id: 'tool-2',
                timestamp: '2024-01-01T00:01:00Z',
                toolArgs: {
                    todos: [
                        { content: 'first', status: 'completed' },
                        { content: 'second', status: 'in_progress', activeForm: 'Doing second thing' },
                    ],
                },
            }),
        ]
        const result = extractCurrentPlan(entries)
        expect(result.todos).toEqual([
            { content: 'first', status: 'completed', activeForm: undefined },
            { content: 'second', status: 'in_progress', activeForm: 'Doing second thing' },
        ])
        expect(result.todosTimestamp).toBe('2024-01-01T00:01:00Z')
    })

    it('extracts plan markdown from the latest ExitPlanMode call', () => {
        const entries: LogEntry[] = [
            toolEntry({
                id: 'plan-1',
                toolName: 'ExitPlanMode',
                timestamp: '2024-01-01T00:00:00Z',
                toolArgs: { plan: '## Old plan\n- step a' },
            }),
            toolEntry({
                id: 'plan-2',
                toolName: 'ExitPlanMode',
                timestamp: '2024-01-01T00:05:00Z',
                toolArgs: { plan: '## New plan\n- step b' },
            }),
        ]
        const result = extractCurrentPlan(entries)
        expect(result.planMarkdown).toBe('## New plan\n- step b')
        expect(result.planTimestamp).toBe('2024-01-01T00:05:00Z')
    })

    it('ignores non-tool entries and unrelated tools', () => {
        const entries: LogEntry[] = [
            { id: 'u-1', type: 'user', message: 'hello' },
            toolEntry({ id: 'tool-1', toolName: 'Read', toolArgs: { file_path: '/etc/hosts' } }),
            toolEntry({
                id: 'tool-2',
                toolArgs: { todos: [{ content: 'only', status: 'pending' }] },
            }),
        ]
        const result = extractCurrentPlan(entries)
        expect(result.todos).toEqual([{ content: 'only', status: 'pending', activeForm: undefined }])
        expect(result.planMarkdown).toBeNull()
    })

    it('skips invalid todo entries without a string content', () => {
        const entries: LogEntry[] = [
            toolEntry({
                toolArgs: {
                    todos: [
                        { content: 'valid', status: 'pending' },
                        { status: 'pending' },
                        null,
                        { content: 123 },
                        { content: 'also valid', status: 'completed' },
                    ],
                },
            }),
        ]
        const result = extractCurrentPlan(entries)
        expect(result.todos).toEqual([
            { content: 'valid', status: 'pending', activeForm: undefined },
            { content: 'also valid', status: 'completed', activeForm: undefined },
        ])
    })

    it('treats an unknown todo status as pending', () => {
        const entries: LogEntry[] = [
            toolEntry({
                toolArgs: { todos: [{ content: 'thing', status: 'made_up_status' }] },
            }),
        ]
        const result = extractCurrentPlan(entries)
        expect(result.todos).toEqual([{ content: 'thing', status: 'pending', activeForm: undefined }])
    })

    it('ignores empty plan strings', () => {
        const entries: LogEntry[] = [toolEntry({ toolName: 'ExitPlanMode', toolArgs: { plan: '   ' } })]
        expect(extractCurrentPlan(entries).planMarkdown).toBeNull()
    })
})
