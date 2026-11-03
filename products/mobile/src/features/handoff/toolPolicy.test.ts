import { parsePermissionRequest } from './permissionRequest'
import {
    defaultPermissionDecision,
    findAllowOptionId,
    isPostHogExecTool,
    type PermissionDecision,
    routePermissionRequest,
} from './toolPolicy'
import type { AgentQuestion, PermissionOption, PermissionRecord } from './types'

function makeRecord(
    overrides: {
        toolName?: string
        rawServerName?: string
        rawToolName?: string
        input?: Record<string, unknown>
        kind?: string
        meta?: unknown
        options?: PermissionOption[]
        questions?: AgentQuestion[]
    } = {}
): PermissionRecord {
    return {
        requestId: 'r',
        toolCallId: 'tc',
        toolName: overrides.toolName ?? 'mcp__posthog__exec',
        options: overrides.options ?? [{ optionId: 'allow', name: 'Yes', kind: 'allow_once', customInput: false }],
        rawToolCall: {
            toolCallId: 'tc',
            rawServerName: overrides.rawServerName ?? 'posthog',
            rawToolName: overrides.rawToolName ?? 'exec',
            input: overrides.input ?? {},
            ...(overrides.kind ? { kind: overrides.kind } : {}),
            meta: overrides.meta,
        },
        ...(overrides.questions ? { questions: overrides.questions } : {}),
    }
}

const BUILT_IN = makeRecord({
    toolName: 'Bash',
    rawServerName: 'claude',
    rawToolName: '',
    meta: { claudeCode: { toolName: 'Bash' } },
})
const QUESTION = makeRecord({
    toolName: 'AskUserQuestion',
    rawServerName: 'claude',
    rawToolName: '',
    meta: { claudeCode: { toolName: 'AskUserQuestion' } },
    questions: [{ question: 'Pick one', multiSelect: false, options: [{ label: 'A' }] }],
})
const PLAN = makeRecord({
    toolName: '',
    rawServerName: 'claude',
    rawToolName: '',
    kind: 'switch_mode',
    input: { plan: '# Plan', toolName: 'ExitPlanMode' },
    options: [{ optionId: 'auto', name: 'Yes, and use "auto" mode', kind: 'allow_always', customInput: false }],
})
const NAMED_PLAN = makeRecord({
    toolName: 'ExitPlanMode',
    rawServerName: 'claude',
    rawToolName: 'ExitPlanMode',
})
const INPUT_PLAN = makeRecord({
    toolName: 'Bash',
    rawServerName: 'claude',
    rawToolName: 'Bash',
    input: { toolName: 'ExitPlanMode' },
})
const RAW_PLAN = makeRecord({
    toolName: '',
    rawServerName: 'claude',
    rawToolName: 'ExitPlanMode',
})
const CONNECTION_CALL = makeRecord({
    input: { command: 'call posthog-connection-call {"connection_id":"1","tool":"execute-sql"}' },
})
const OTHER_MCP = makeRecord({ toolName: 'mcp__other__foo', rawServerName: 'other', rawToolName: 'foo' })

describe('toolPolicy', () => {
    test.each([
        ['mcp__posthog__exec', true],
        ['mcp__posthog_us__exec', true],
        ['mcp__plugin_posthog__exec', true],
        ['mcp__posthog__query', false],
        ['Bash', false],
    ])('isPostHogExecTool(%s) is %s', (name, expected) => {
        expect(isPostHogExecTool(name)).toBe(expected)
    })

    test.each<[string, PermissionRecord, PermissionDecision]>([
        ['built-in tool', BUILT_IN, 'prompt'],
        ['exec discovery verb', makeRecord({ input: { command: 'tools' } }), 'prompt'],
        ['exec create', makeRecord({ input: { command: 'call insight-create {"name":"Signups"}' } }), 'prompt'],
        ['exec delete', makeRecord({ input: { command: 'call feature-flag-delete {"key":"x"}' } }), 'prompt'],
        [
            'exec call with flags before the sub-tool',
            makeRecord({ input: { command: 'call --json --confirm insight-get {}' } }),
            'prompt',
        ],
        ['exec call with no sub-tool', makeRecord({ input: { command: 'call --json' } }), 'prompt'],
        ['connection call', CONNECTION_CALL, 'prompt'],
        [
            'connection forward',
            makeRecord({
                input: { command: 'call posthog-connection-forward {"connection_id":"1","method":"GET","path":"x"}' },
            }),
            'prompt',
        ],
        ['unidentified frame', makeRecord({ toolName: '', rawServerName: 'claude', rawToolName: '' }), 'prompt'],
        ['other mcp tool', OTHER_MCP, 'prompt'],
        ['question request', QUESTION, 'prompt'],
        ['plan approval with no tool name', PLAN, 'prompt'],
        ['named plan approval', NAMED_PLAN, 'prompt'],
        ['plan approval inside input', INPUT_PLAN, 'prompt'],
        ['plan approval in raw tool name', RAW_PLAN, 'prompt'],
    ])('defaultPermissionDecision: %s', (_name, record, expected) => {
        expect(defaultPermissionDecision(record)).toBe(expected)
    })

    test.each(
        ['default', 'auto', 'plan', 'bypassPermissions'].flatMap((mode) =>
            ['mcp__posthog__exec', 'Bash', 'ExampleTool'].map((toolName) => ({ mode, toolName }))
        )
    )('relayed $toolName operations remain manual in $mode', ({ mode, toolName }) => {
        const record = parsePermissionRequest({
            requestId: 'example-request',
            options: [{ optionId: 'allow', kind: 'allow_once', name: 'Allow' }],
            toolCall: {
                toolCallId: 'example-call',
                rawInput: { command: 'call --confirm dashboard-delete {"id":123}' },
                _meta: { claudeCode: { toolName } },
            },
        })
        expect(record).not.toBeNull()
        expect(routePermissionRequest(record as PermissionRecord, { mode, replayed: false })).toEqual({
            action: 'prompt',
        })
    })

    test.each<[string, PermissionOption[], string | null]>([
        [
            'prefers allow_once over allow_always',
            [
                { optionId: 'aa', name: '', kind: 'allow_always', customInput: false },
                { optionId: 'a1', name: '', kind: 'allow_once', customInput: false },
            ],
            'a1',
        ],
        [
            'falls back to allow_always',
            [
                { optionId: 'aa', name: '', kind: 'allow_always', customInput: false },
                { optionId: 'r', name: '', kind: 'reject_once', customInput: false },
            ],
            'aa',
        ],
        ['no allow option', [{ optionId: 'r', name: '', kind: 'reject_once', customInput: false }], null],
    ])('findAllowOptionId: %s', (_name, options, expected) => {
        expect(findAllowOptionId(makeRecord({ options }))).toBe(expected)
    })

    test.each<[string, PermissionRecord, { mode?: string; replayed: boolean }, string]>([
        ['live built-in requires consent', BUILT_IN, { replayed: false }, 'prompt'],
        ['replayed built-in is never answered for the user', BUILT_IN, { replayed: true }, 'prompt'],
        [
            'full auto preserves approval for another MCP server',
            OTHER_MCP,
            { mode: 'bypassPermissions', replayed: false },
            'prompt',
        ],
        ['full auto still asks a question', QUESTION, { mode: 'bypassPermissions', replayed: false }, 'prompt'],
        ['full auto still asks to approve a plan', PLAN, { mode: 'bypassPermissions', replayed: false }, 'prompt'],
        ['default mode still asks to approve a named plan', NAMED_PLAN, { replayed: false }, 'prompt'],
        ['auto mode still asks to approve a plan in input', INPUT_PLAN, { mode: 'auto', replayed: false }, 'prompt'],
        [
            'full auto still asks to approve a raw plan',
            RAW_PLAN,
            { mode: 'bypassPermissions', replayed: false },
            'prompt',
        ],
        [
            'full auto still asks to approve a named plan',
            NAMED_PLAN,
            { mode: 'bypassPermissions', replayed: false },
            'prompt',
        ],
        [
            'full auto still asks for a connected project',
            CONNECTION_CALL,
            { mode: 'bypassPermissions', replayed: false },
            'prompt',
        ],
        [
            'raw-input external tool requires consent',
            makeRecord({
                toolName: '',
                rawServerName: 'claude',
                rawToolName: '',
                input: { toolName: 'mcp__example__send', arguments: { destination: 'example.com' } },
            }),
            { mode: 'bypassPermissions', replayed: false },
            'prompt',
        ],
        ['other modes keep the default policy', OTHER_MCP, { mode: 'auto', replayed: false }, 'prompt'],
    ])('routePermissionRequest: %s', (_name, record, context, expected) => {
        expect(routePermissionRequest(record, context).action).toBe(expected)
    })
})
