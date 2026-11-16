import type { ModelChoiceApi } from '@/api/tasks'

import { STATIC_CATALOGUE } from '../handoff/runOptions'
import {
    type ChatRunOptions,
    chatRunOptionsFromConfig,
    chatRunOptionsReducer,
    chipModelLabel,
    DEFAULT_CHAT_RUN_OPTIONS,
} from './chatRunOptions'
import type { SessionRunConfig } from './session/sessionRun'

const CATALOGUE: ModelChoiceApi[] = STATIC_CATALOGUE

describe('chat run options', () => {
    test.each<[string, ChatRunOptions['model'], string]>([
        ['an untouched model', 'default', 'Default'],
        [
            'a Claude model with an effort',
            { runtimeAdapter: 'claude', model: 'claude-opus-5-5', reasoningEffort: 'high' },
            'Opus 5.5 · High',
        ],
        [
            'a model without efforts',
            { runtimeAdapter: 'claude', model: 'moonshotai/kimi-k3', reasoningEffort: null },
            'Kimi K3',
        ],
        [
            'a Codex model',
            { runtimeAdapter: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'xhigh' },
            'GPT-6.1 Sol · Extra high',
        ],
    ])('labels the model chip for %s', (_, model, label) => {
        expect(chipModelLabel(CATALOGUE, model)).toBe(label)
    })

    it('maps a mode the new harness lacks when a model is pinned', () => {
        const asking = chatRunOptionsReducer(DEFAULT_CHAT_RUN_OPTIONS, { type: 'mode', mode: 'default' })
        const codex = chatRunOptionsReducer(asking, {
            type: 'model',
            model: { runtimeAdapter: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'high' },
            runtimeAdapter: 'codex',
        })
        expect(codex.permissionMode).toBe('auto')
    })

    test.each<[string, SessionRunConfig, boolean, ChatRunOptions]>([
        [
            'a run with a known model and mode',
            { runtimeAdapter: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'xhigh', permissionMode: 'plan' },
            true,
            {
                model: { runtimeAdapter: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'xhigh' },
                permissionMode: 'plan',
            },
        ],
        [
            'values the app does not know',
            { runtimeAdapter: 'claude', model: 'claude-opus-5-5', reasoningEffort: 'turbo', permissionMode: 'yolo' },
            true,
            {
                model: { runtimeAdapter: 'claude', model: 'claude-opus-5-5', reasoningEffort: null },
                permissionMode: 'auto',
            },
        ],
        [
            'a run with no known harness',
            { runtimeAdapter: null, model: 'claude-opus-5-5', reasoningEffort: 'high', permissionMode: null },
            true,
            DEFAULT_CHAT_RUN_OPTIONS,
        ],
        [
            'a newly started run with a resolved model and mode',
            { runtimeAdapter: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'xhigh', permissionMode: 'plan' },
            false,
            { model: 'default', permissionMode: 'plan' },
        ],
    ])('seeds the options from %s', (_, config, pinModel, expected) => {
        expect(chatRunOptionsFromConfig(config, pinModel)).toEqual(expected)
    })
})
