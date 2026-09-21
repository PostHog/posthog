import type { PermissionRequestRecord, ToolInvocation } from '../types/streamTypes'
import type { PermissionOption } from '../types/wireTypes'
import type { AgentQuestion } from './questionUtils'
import {
    defaultPermissionDecision,
    findAllowOptionId,
    isDestructiveChatActionTool,
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
            ['exec update', makeRecord({ input: { command: 'call insight-update {"id":"abc"}' } }), 'auto_allow'],
            ['exec publish', makeRecord({ input: { command: 'call workflows-publish {"id":"w1"}' } }), 'auto_allow'],
            [
                'exec delete',
                makeRecord({ input: { command: 'call feature-flag-delete {"key":"new-nav"}' } }),
                'auto_allow',
            ],
            ['exec call with no sub-tool', makeRecord({ input: { command: 'call --json' } }), 'auto_allow'],
            [
                'connection call running a read',
                makeRecord({
                    input: {
                        command: 'call posthog-connection-call {"connection_id":"1","tool":"execute-sql"}',
                    },
                }),
                'prompt',
            ],
            [
                'connection call running a delete',
                makeRecord({
                    input: {
                        command: 'call posthog-connection-call {"connection_id":"1","tool":"feature-flag-delete"}',
                    },
                }),
                'prompt',
            ],
            [
                'connection forward',
                makeRecord({
                    input: {
                        command:
                            'call posthog-connection-forward {"connection_id":"1","method":"GET","path":"api/projects/2/insights/"}',
                    },
                }),
                'prompt',
            ],
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

        // With chat actions on, a click and a typed request both land on the same card for the
        // destructive workflow tools; without the flag the policy must not change at all.
        it.each<[string, string, boolean, PermissionDecision]>([
            ['workflows-enable', 'call workflows-enable {"id":"w1"}', true, 'prompt'],
            ['workflows-publish', 'call workflows-publish {"id":"w1"}', true, 'prompt'],
            ['workflows-enable with the flag off', 'call workflows-enable {"id":"w1"}', false, 'auto_allow'],
            ['a non-destructive workflow tool', 'call workflows-create {"name":"x"}', true, 'auto_allow'],
            // The server strips every flag in EXEC_CALL_FLAGS before the sub-tool, so the gate must too.
            ['workflows-enable behind --no-skills', 'call --no-skills workflows-enable {"id":"w1"}', true, 'prompt'],
            [
                'workflows-enable behind two flags',
                'call --json --no-skills workflows-enable {"id":"w1"}',
                true,
                'prompt',
            ],
            [
                'workflows-enable behind two flags with the flag off',
                'call --json --no-skills workflows-enable {"id":"w1"}',
                false,
                'auto_allow',
            ],
            // A call whose sub-tool cannot be read fails closed under the flag and stays as it was without it.
            ['an unparsable call', 'call --json', true, 'prompt'],
            ['a call behind an unknown flag', 'call --later workflows-enable {"id":"w1"}', true, 'prompt'],
            ['an unparsable call with the flag off', 'call --json', false, 'auto_allow'],
            ['a discovery verb', 'search workflows', true, 'auto_allow'],
        ])('%s → %s', (_case, command, chatActionsEnabled, expected) => {
            expect(defaultPermissionDecision(makeRecord({ input: { command } }), { chatActionsEnabled })).toEqual(
                expected
            )
        })
    })

    describe('isDestructiveChatActionTool', () => {
        it.each([
            ['call workflows-publish {"id":"w1"}', true],
            ['call --confirm WORKFLOWS-ENABLE {"id":"w1"}', true],
            ['call workflows-create {}', false],
            ['call --json', false],
        ])('%s → %s', (command, expected) => {
            expect(isDestructiveChatActionTool(makeRecord({ input: { command } }))).toBe(expected)
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
