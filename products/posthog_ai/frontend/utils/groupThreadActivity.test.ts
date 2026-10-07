import type { ThreadItem, ToolInvocation } from '../types/streamTypes'
import { activityWindow, groupConsecutiveTools, groupThreadActivity, groupToolRuns } from './groupThreadActivity'

describe('thread activity grouping', () => {
    const tool = (id: string, startedAt = 1000): ThreadItem => ({
        id,
        type: 'tool_invocation',
        toolCallId: id,
        startedAt,
        endedAt: startedAt + 100,
    })

    it('keeps messages, artifacts, failures and turn boundaries in order, without duplicating calls', () => {
        const items: ThreadItem[] = [
            { id: 'human', type: 'human_message', text: 'Find a report' },
            tool('search'),
            { id: 'thought', type: 'assistant_thought', text: 'Checking results', startedAt: 1100 },
            { id: 'notification', type: 'task_notification', status: 'completed', startedAt: 1200 },
            tool('chart', 1300),
            tool('read', 1400),
            { id: 'failure', type: 'task_notification', status: 'failed' },
            { id: 'answer', type: 'assistant_message', text: 'Here is the report', startedAt: 1600 },
            { id: 'end', type: 'turn_separator', startedAt: 1700 },
            tool('next', 3000),
        ]
        const result = groupThreadActivity(items, new Set(['chart']))
        expect(result.map((item) => item.id)).toEqual([
            'human',
            'activity-search',
            'chart',
            'activity-read',
            'failure',
            'answer',
            'end',
            'activity-next',
        ])
        expect(result.flatMap((item) => (item.type === 'activity_group' ? item.items : [item]))).toEqual(items)
        expect(result[1]).toMatchObject({ startedAt: 1000, endedAt: 1300 })
        expect(groupThreadActivity([...items, tool('last', 3200)], new Set(['chart'])).at(-1)?.id).toBe('activity-next')
    })

    it('folds tool runs like PostHog Desktop, keeping plans, lone calls and the final chart of a closed run visible', () => {
        const calls = new Map<string, ToolInvocation>()
        const call = (id: string, status: ToolInvocation['status'] = 'completed'): ThreadItem => {
            calls.set(id, {
                toolCallId: id,
                rawServerName: 'posthog',
                rawToolName: 'exec',
                input: {},
                status,
                contentBlocks: [],
            })
            return tool(id)
        }
        const thought = (id: string): ThreadItem => ({ id, type: 'assistant_thought', text: 'Checking' })
        const prose = (id: string): ThreadItem => ({ id, type: 'assistant_message', text: 'Found it' })
        const items: ThreadItem[] = [
            { id: 'human', type: 'human_message', text: 'Why did signups drop?' },
            { id: 'setup', type: 'status', status: 'setup_hooks' },
            { id: 'init', type: 'status', status: 'sdk_initialization' },
            thought('plan'),
            call('read'),
            thought('between'),
            call('grep'),
            prose('first-answer'),
            call('lone'),
            thought('after-lone'),
            call('plan-card'),
            call('schema'),
            call('chart'),
            prose('chart-answer'),
            { id: 'end', type: 'turn_separator' },
            call('live-chart'),
        ]
        const options = { pinnedToolIds: new Set(['plan-card']), widgetToolIds: new Set(['chart', 'live-chart']) }
        const result = groupToolRuns(items, calls, { ...options, settled: false })
        expect(result.map((item) => item.id)).toEqual([
            'human',
            'init',
            'activity-read',
            'first-answer',
            'lone',
            'after-lone',
            'plan-card',
            'schema',
            'chart',
            'chart-answer',
            'end',
            'activity-live-chart',
        ])
        expect(result[2]).toMatchObject({ items: [thought('plan'), tool('read'), thought('between'), tool('grep')] })
        expect(result.flatMap((item) => (item.type === 'activity_group' ? item.items : [item]))).toEqual(
            items.filter((item) => item.id !== 'setup')
        )
        expect(groupToolRuns(items, calls, { ...options, settled: true }).at(-1)?.id).toBe('live-chart')
    })

    it('does not invent a duration when part of the group has no recorded start', () => {
        const result = groupThreadActivity(
            [tool('timed'), { id: 'imported', type: 'tool_invocation', toolCallId: 'imported' }],
            new Set()
        )
        expect(result[0].startedAt).toBeUndefined()
    })

    it('chains only adjacent calls to the same resolved tool and server, retaining every item', () => {
        const calls = new Map<string, ToolInvocation>()
        const call = (id: string, name: string, server = 'posthog'): ThreadItem => {
            calls.set(id, {
                toolCallId: id,
                rawServerName: server,
                rawToolName: 'exec',
                input: { command: `call ${name} {}` },
                status: 'completed',
                contentBlocks: [],
            })
            return tool(id)
        }
        const items = [
            call('a', 'execute-sql'),
            call('b', 'execute-sql'),
            call('c', 'query-trends'),
            call('d', 'execute-sql'),
            { id: 'thought', type: 'assistant_thought', text: 'Check another source.' } as ThreadItem,
            call('e', 'execute-sql'),
            call('f', 'execute-sql', 'other'),
            tool('missing'),
            call('g', 'execute-sql'),
        ]
        const groups = groupConsecutiveTools(items, calls)
        expect(groups.map((group) => group.map((item) => item.id))).toEqual([
            ['a', 'b'],
            ['c'],
            ['d'],
            ['thought'],
            ['e'],
            ['f'],
            ['missing'],
            ['g'],
        ])
        expect(groups.flat()).toEqual(items)
    })

    it.each([0, 1, 10, 11, 300])('shows every one of %i activities with at most one click', (count) => {
        const items = Array.from({ length: count }, (_, i) => i)
        const collapsed = activityWindow(items, false)
        expect(collapsed.first.length + collapsed.last.length).toBeLessThanOrEqual(10)
        expect(collapsed.middle).toEqual([])
        expect(collapsed.hiddenCount).toBe(count > 10 ? count - 5 : 0)
        const open = activityWindow(items, true)
        expect([...open.first, ...open.middle, ...open.last]).toEqual(items)
    })
})
