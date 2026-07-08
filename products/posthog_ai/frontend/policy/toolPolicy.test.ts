import type { PermissionRequestRecord, ToolInvocation } from '../types/streamTypes'
import type { PermissionOption } from '../types/wireTypes'
import type { AgentQuestion } from './questionUtils'
import {
    defaultPermissionDecision,
    findAllowOptionId,
    isPostHogDestructiveSubTool,
    isPostHogExecTool,
    type PermissionDecision,
} from './toolPolicy'

function makeRecord(
    overrides: {
        toolName?: string
        rawServerName?: string
        rawToolName?: string
        input?: Record<string, unknown>
        meta?: unknown
        options?: PermissionOption[]
        questions?: AgentQuestion[]
    } = {}
): PermissionRequestRecord {
    const rawToolCall: ToolInvocation = {
        toolCallId: 'tc',
        rawServerName: overrides.rawServerName ?? 'posthog',
        rawToolName: overrides.rawToolName ?? 'exec',
        input: overrides.input ?? {},
        status: 'pending',
        contentBlocks: [],
        meta: overrides.meta,
    }
    return {
        requestId: 'r',
        toolCallId: 'tc',
        toolName: overrides.toolName ?? 'mcp__posthog__exec',
        options: overrides.options ?? [{ optionId: 'allow', name: 'Yes', kind: 'allow_once' }],
        rawToolCall,
        ...(overrides.questions ? { questions: overrides.questions } : {}),
    }
}

describe('toolPolicy', () => {
    describe('isPostHogExecTool', () => {
        it.each([
            ['mcp__posthog__exec', true],
            ['mcp__posthog_us__exec', true],
            ['mcp__posthog__query', false],
            ['Bash', false],
        ])('%s → %s', (name, expected) => {
            expect(isPostHogExecTool(name)).toEqual(expected)
        })
    })

    describe('isPostHogDestructiveSubTool', () => {
        // Cases ported from Twig posthog-exec-gate.test.ts.
        it.each([
            'experiment-update',
            'feature-flag-delete',
            'notebooks-destroy',
            'experiment-partial-update',
            'update-something',
            'delete',
        ])('%s is destructive', (sub) => expect(isPostHogDestructiveSubTool(sub)).toBe(true))
        it.each(['experiment-get', 'feature-flag-list', 'experiment-create', 'insights-pause', 'get-updated-events'])(
            '%s is not destructive',
            (sub) => expect(isPostHogDestructiveSubTool(sub)).toBe(false)
        )
    })

    describe('defaultPermissionDecision', () => {
        it.each<[string, PermissionRequestRecord, PermissionDecision]>([
            [
                'built-in tool',
                makeRecord({
                    toolName: 'Bash',
                    rawServerName: 'claude',
                    rawToolName: '',
                    meta: { claudeCode: { toolName: 'Bash' } },
                }),
                'auto_allow',
            ],
            ['exec discovery verb', makeRecord({ input: { command: 'tools' } }), 'auto_allow'],
            ['exec create', makeRecord({ input: { command: 'call insight-create {"name":"Signups"}' } }), 'auto_allow'],
            ['exec update', makeRecord({ input: { command: 'call insight-update {"id":"abc"}' } }), 'prompt'],
            ['exec delete', makeRecord({ input: { command: 'call feature-flag-delete {"key":"new-nav"}' } }), 'prompt'],
            // A destructive sub-tool hidden behind --confirm/--json (in any order) must still prompt —
            // the inner tool name is resolved after the flags, not as the flag token.
            [
                'exec delete behind --confirm',
                makeRecord({ input: { command: 'call --confirm feature-flag-delete {"key":"x"}' } }),
                'prompt',
            ],
            [
                'exec delete behind --confirm --json',
                makeRecord({ input: { command: 'call --confirm --json feature-flag-delete {"key":"x"}' } }),
                'prompt',
            ],
            [
                'exec delete behind --json --confirm',
                makeRecord({ input: { command: 'call --json --confirm feature-flag-delete {"key":"x"}' } }),
                'prompt',
            ],
            // An exec call we can't resolve to a concrete sub-tool fails closed.
            ['exec call with no sub-tool', makeRecord({ input: { command: 'call --json' } }), 'prompt'],
            // A permission frame carrying no canonical tool name isn't a positively-identified built-in.
            [
                'unidentified frame',
                makeRecord({ toolName: '', rawServerName: 'claude', rawToolName: '', input: {} }),
                'prompt',
            ],
            [
                'other mcp tool',
                makeRecord({ toolName: 'mcp__other__foo', rawServerName: 'other', rawToolName: 'foo' }),
                'prompt',
            ],
            // AskUserQuestion rides the permission framework with allow_once options, but must never
            // auto-approve — picking option_0 with no answers gets rejected by the agent.
            [
                'question request',
                makeRecord({
                    toolName: 'AskUserQuestion',
                    rawServerName: 'claude',
                    rawToolName: '',
                    meta: { claudeCode: { toolName: 'AskUserQuestion' } },
                    questions: [{ question: 'Pick one', multiSelect: false, options: [{ label: 'A' }] }],
                }),
                'prompt',
            ],
        ])('%s → %s', (_case, record, expected) => {
            expect(defaultPermissionDecision(record)).toEqual(expected)
        })
    })

    describe('findAllowOptionId', () => {
        it('prefers allow_once over allow_always', () => {
            const id = findAllowOptionId(
                makeRecord({
                    options: [
                        { optionId: 'aa', name: '', kind: 'allow_always' },
                        { optionId: 'a1', name: '', kind: 'allow_once' },
                    ],
                })
            )
            expect(id).toEqual('a1')
        })

        it('falls back to allow_always when there is no allow_once', () => {
            const id = findAllowOptionId(
                makeRecord({
                    options: [
                        { optionId: 'aa', name: '', kind: 'allow_always' },
                        { optionId: 'r', name: '', kind: 'reject_once' },
                    ],
                })
            )
            expect(id).toEqual('aa')
        })

        it('returns null when no allow option exists', () => {
            expect(
                findAllowOptionId(makeRecord({ options: [{ optionId: 'r', name: '', kind: 'reject_once' }] }))
            ).toBeNull()
        })
    })
})
