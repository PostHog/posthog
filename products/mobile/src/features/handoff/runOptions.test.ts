import type { HandoffRunFieldsApi, ModelChoiceApi, PermissionModeApi, ResolvedAiRunDefaultsApi } from '@/api/tasks'

import {
    buildHandoffRunRequest,
    DEFAULT_RUN_OPTIONS,
    modelDisplayName,
    modesForRuntimeAdapter,
    offeredModels,
    pinModel,
    type RunOptions,
    resolveEffortForModel,
    resolveModeForRuntimeAdapter,
} from './runOptions'

const CATALOGUE: ModelChoiceApi[] = [
    {
        runtime_adapter: 'claude',
        model: 'claude-opus-5-5',
        display_name: 'Claude Opus 5.5',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '2×',
        offered: true,
    },
    {
        runtime_adapter: 'claude',
        model: 'claude-sonnet-4-6',
        display_name: 'Claude Sonnet 4.6',
        supported_efforts: ['low', 'medium', 'high'],
        offered: false,
    },
    {
        runtime_adapter: 'claude',
        model: 'moonshotai/kimi-k3',
        display_name: 'Kimi K3',
        supported_efforts: [],
        offered: true,
    },
    {
        runtime_adapter: 'codex',
        model: 'gpt-5.5',
        display_name: 'GPT-5.5',
        supported_efforts: ['low', 'medium', 'xhigh'],
        offered: true,
    },
]

function defaults(model: string | null, runtimeAdapter: string | null = null): ResolvedAiRunDefaultsApi {
    return {
        runtime: 'acp',
        runtime_adapter: runtimeAdapter,
        model,
        reasoning_effort: model ? 'medium' : null,
        source: model ? 'user' : 'none',
    }
}

const PI_DEFAULTS: ResolvedAiRunDefaultsApi = {
    runtime: 'pi',
    runtime_adapter: null,
    model: 'moonshotai/kimi-k3',
    reasoning_effort: null,
    source: 'user',
}

function options(change: Partial<RunOptions>): RunOptions {
    return { ...DEFAULT_RUN_OPTIONS, ...change }
}

describe('runOptions', () => {
    test.each<[string, RunOptions, ResolvedAiRunDefaultsApi | undefined, HandoffRunFieldsApi]>([
        [
            'untouched model with a stored default sends only the mode',
            DEFAULT_RUN_OPTIONS,
            defaults('claude-sonnet-5-5', 'claude'),
            { initial_permission_mode: 'auto' },
        ],
        [
            'untouched model with a Codex default maps the mode to Codex and pins nothing',
            options({ permissionMode: 'acceptEdits' }),
            defaults('gpt-5.5', 'codex'),
            { initial_permission_mode: 'auto' },
        ],
        [
            'untouched model with a Pi default pins the Inbox fallback, as ACP runs discard it',
            options({ permissionMode: 'acceptEdits' }),
            PI_DEFAULTS,
            {
                runtime_adapter: 'claude',
                model: 'claude-opus-5-5',
                reasoning_effort: 'high',
                initial_permission_mode: 'acceptEdits',
            },
        ],
        [
            'untouched model with no stored default pins the Inbox fallback',
            options({ permissionMode: 'read-only' }),
            defaults(null),
            {
                runtime_adapter: 'claude',
                model: 'claude-opus-5-5',
                reasoning_effort: 'high',
                initial_permission_mode: 'plan',
            },
        ],
        [
            'untouched model with unknown defaults lets the server resolve them',
            options({ branch: '  release  ' }),
            undefined,
            { initial_permission_mode: 'auto', branch: 'release' },
        ],
        [
            'a picked Codex model sends the triple and a Codex mode',
            options({
                model: { runtimeAdapter: 'codex', model: 'gpt-5.5', reasoningEffort: 'xhigh' },
                permissionMode: 'acceptEdits',
            }),
            defaults('claude-sonnet-5-5', 'claude'),
            { runtime_adapter: 'codex', model: 'gpt-5.5', reasoning_effort: 'xhigh', initial_permission_mode: 'auto' },
        ],
        [
            'a picked model with no efforts leaves the effort out',
            options({
                model: { runtimeAdapter: 'claude', model: 'moonshotai/kimi-k3', reasoningEffort: null },
                branch: ' ',
            }),
            defaults(null),
            { runtime_adapter: 'claude', model: 'moonshotai/kimi-k3', initial_permission_mode: 'auto' },
        ],
    ])('buildHandoffRunRequest: %s', (_name, picked, resolved, expected) => {
        expect(buildHandoffRunRequest(picked, resolved)).toEqual(expected)
    })

    test.each<[string, string | null, string, string]>([
        ['keeps a supported effort', 'medium', 'claude-sonnet-4-6', 'medium'],
        ['clamps an effort the model lacks to high', 'max', 'claude-sonnet-4-6', 'high'],
        ['falls back to the highest effort when high is missing', 'max', 'gpt-5.5', 'xhigh'],
        ['reads a provider-qualified id', 'ultracode', 'anthropic/claude-opus-5-5', 'ultracode'],
        ['gives a model with no efforts the default', 'max', 'moonshotai/kimi-k3', 'high'],
        ['gives a model the list does not describe the default', 'max', 'claude-opus-4-1', 'high'],
    ])('resolveEffortForModel %s', (_name, effort, model, expected) => {
        expect(resolveEffortForModel(CATALOGUE, effort, model)).toBe(expected)
    })

    test.each<[string, string, string | null]>([
        ['a model that supports the carried effort', 'claude-opus-5-5', 'ultracode'],
        ['a model that lacks the carried effort', 'claude-sonnet-4-6', 'high'],
        ['a model with no efforts', 'moonshotai/kimi-k3', null],
    ])('pinModel for %s', (_name, model, expected) => {
        const option = CATALOGUE.find((entry) => entry.model === model) as ModelChoiceApi
        expect(pinModel(CATALOGUE, option, 'ultracode').reasoningEffort).toBe(expected)
    })

    test('pinning a model the list does not describe pins no effort', () => {
        const option: ModelChoiceApi = {
            runtime_adapter: 'claude',
            model: 'claude-opus-4-1',
            display_name: 'Claude Opus 4.1',
            supported_efforts: ['low', 'high'],
            offered: true,
        }
        expect(pinModel(CATALOGUE, option, 'high').reasoningEffort).toBeNull()
    })

    test.each<[string, string | undefined, string[]]>([
        ['hides an unoffered model', undefined, ['claude-opus-5-5', 'moonshotai/kimi-k3', 'gpt-5.5']],
        [
            'keeps an unoffered model that is the kept model',
            'anthropic/claude-sonnet-4-6',
            ['claude-opus-5-5', 'claude-sonnet-4-6', 'moonshotai/kimi-k3', 'gpt-5.5'],
        ],
        [
            'ignores a kept model that is already offered',
            'gpt-5.5',
            ['claude-opus-5-5', 'moonshotai/kimi-k3', 'gpt-5.5'],
        ],
        [
            'ignores a kept model the list does not have',
            'claude-opus-4-1',
            ['claude-opus-5-5', 'moonshotai/kimi-k3', 'gpt-5.5'],
        ],
    ])('offeredModels %s', (_name, keepModel, expected) => {
        expect(offeredModels(CATALOGUE, keepModel).map((option) => option.model)).toEqual(expected)
    })

    test.each<[string, string, string]>([
        ['a listed model', 'claude-opus-5-5', 'Claude Opus 5.5'],
        ['a provider-qualified id', 'anthropic/claude-opus-5-5', 'Claude Opus 5.5'],
        ['a model the list lacks', 'claude-opus-4-1', 'claude-opus-4-1'],
    ])('modelDisplayName for %s', (_name, model, expected) => {
        expect(modelDisplayName(CATALOGUE, model)).toBe(expected)
    })

    test.each<['claude' | 'codex', PermissionModeApi, PermissionModeApi]>([
        ['codex', 'default', 'auto'],
        ['codex', 'bypassPermissions', 'full-access'],
        ['codex', 'plan', 'plan'],
        ['claude', 'read-only', 'plan'],
        ['claude', 'full-access', 'bypassPermissions'],
    ])('resolveModeForRuntimeAdapter(%s, %s) is %s', (adapter, mode, expected) => {
        expect(resolveModeForRuntimeAdapter(adapter, mode)).toBe(expected)
    })

    test('the pickers hide the never-ask modes', () => {
        expect(modesForRuntimeAdapter('claude').map((option) => option.value)).toEqual([
            'default',
            'acceptEdits',
            'plan',
            'auto',
        ])
        expect(modesForRuntimeAdapter('codex').map((option) => option.value)).toEqual(['plan', 'read-only', 'auto'])
    })
})
