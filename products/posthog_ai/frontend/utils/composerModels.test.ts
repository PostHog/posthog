import { RuntimeAdapterEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { type ComposerModelOption, groupModelsByRuntimeAdapter } from './composerModels'

describe('composerModels', () => {
    // New models get appended to COMPOSER_MODELS as they ship, so a Claude model can land after the Codex
    // ones. Each harness must still render as one section — two "Claude Code" headers would read as two
    // different harnesses.
    it('groups models under one section per harness, in first-seen order', () => {
        const models: ComposerModelOption[] = [
            { value: 'claude-sonnet-5', label: 'Claude Sonnet 5', runtimeAdapter: RuntimeAdapterEnumApi.Claude },
            { value: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', runtimeAdapter: RuntimeAdapterEnumApi.Codex },
            { value: 'claude-opus-5', label: 'Claude Opus 5', runtimeAdapter: RuntimeAdapterEnumApi.Claude },
        ]

        expect(groupModelsByRuntimeAdapter(models)).toEqual([
            {
                adapter: RuntimeAdapterEnumApi.Claude,
                label: 'Claude Code',
                models: [models[0], models[2]],
            },
            {
                adapter: RuntimeAdapterEnumApi.Codex,
                label: 'Codex',
                models: [models[1]],
            },
        ])
    })
})
