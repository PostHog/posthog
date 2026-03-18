import type { LLMProviderKey } from '../settings/llmProviderKeysLogic'
import {
    isTraceLikeSelection,
    matchClosestModel,
    matchClosestModelOption,
    type MatchModelOption,
    resolveTraceModelSelection,
} from './playgroundModelMatching'

const model = (id: string, providerKeyId?: string): MatchModelOption => ({ id, providerKeyId })

const providerKey = (id: string, provider: string, state: string = 'ok'): LLMProviderKey =>
    ({ id, provider, state }) as LLMProviderKey

describe('playgroundModelMatching', () => {
    describe('isTraceLikeSelection', () => {
        it.each([
            { model: undefined, provider: undefined, expected: false },
            { model: 'gpt-4', provider: undefined, expected: false },
            { model: undefined, provider: 'openai', expected: true },
            { model: 'gpt-4', provider: 'openai', expected: true },
            { model: 'anthropic/claude-sonnet-4', provider: undefined, expected: true },
            { model: 'openrouter/anthropic/claude-3-opus', provider: undefined, expected: true },
            { model: '', provider: undefined, expected: false },
            { model: '', provider: '', expected: false },
            { model: 'gpt-4', provider: '', expected: false },
        ])('($model, $provider) => $expected', ({ model, provider, expected }) => {
            expect(isTraceLikeSelection(model, provider)).toBe(expected)
        })
    })

    describe('matchClosestModel', () => {
        const models = [
            model('gpt-4.1'),
            model('gpt-4.1-mini'),
            model('gpt-5'),
            model('gpt-5-mini'),
            model('claude-3-opus'),
        ]

        it.each([
            { target: 'gpt-5', expected: 'gpt-5' },
            { target: 'gpt-5-mini', expected: 'gpt-5-mini' },
            { target: 'claude-3-opus', expected: 'claude-3-opus' },
            { target: 'GPT-5', expected: 'gpt-5' },
            { target: 'gpt-5-2025-08-07', expected: 'gpt-5' },
            { target: 'gpt-5-mini-turbo-2025', expected: 'gpt-5-mini' },
            { target: 'llama-3-70b', expected: 'gpt-5-mini' },
            { target: '', expected: 'gpt-5-mini' },
        ])('$target => $expected', ({ target, expected }) => {
            expect(matchClosestModel(target, models)).toBe(expected)
        })

        it('returns default when no models available', () => {
            expect(matchClosestModel('gpt-5', [])).toBe('gpt-5-mini')
        })
    })

    describe('matchClosestModelOption', () => {
        it('prefers exact match', () => {
            const models = [model('gpt-5'), model('gpt-5-mini')]
            expect(matchClosestModelOption('gpt-5', models)?.id).toBe('gpt-5')
        })

        it('prefers case-insensitive exact match', () => {
            const models = [model('GPT-5'), model('gpt-5-mini')]
            expect(matchClosestModelOption('gpt-5', models)?.id).toBe('GPT-5')
        })

        it('matches by namespace variant stripping', () => {
            const models = [model('claude-sonnet-4'), model('gpt-5')]
            expect(matchClosestModelOption('anthropic/claude-sonnet-4', models)?.id).toBe('claude-sonnet-4')
        })

        it('picks preferred provider key among duplicates', () => {
            const models = [model('gpt-5', 'key-b'), model('gpt-5', 'key-a')]
            const keys = [providerKey('key-b', 'openai'), providerKey('key-a', 'openai')]
            const result = matchClosestModelOption('gpt-5', models, keys)
            expect(result?.providerKeyId).toBe('key-a')
        })

        it('returns null for empty model list', () => {
            expect(matchClosestModelOption('gpt-5', [])).toBeNull()
        })
    })

    describe('resolveTraceModelSelection', () => {
        const trialModels = [model('gpt-5'), model('gpt-5-mini'), model('claude-sonnet-4')]

        it('resolves exact match from available models', () => {
            const result = resolveTraceModelSelection('claude-sonnet-4', 'anthropic', trialModels, [])
            expect(result.resolvedModelId).toBe('claude-sonnet-4')
        })

        it('resolves gateway-style model by stripping namespace', () => {
            const result = resolveTraceModelSelection('anthropic/claude-sonnet-4', 'anthropic', trialModels, [])
            expect(result.resolvedModelId).toBe('claude-sonnet-4')
        })

        it('resolves snapshot model ID via prefix matching', () => {
            const result = resolveTraceModelSelection('gpt-5-2025-08-07', 'openai', trialModels, [])
            expect(result.resolvedModelId).toBe('gpt-5')
        })

        it('falls back to raw model ID when no match found', () => {
            const result = resolveTraceModelSelection('llama-3-70b', 'meta', trialModels, [])
            expect(result.resolvedModelId).toBe('llama-3-70b')
        })

        it('resolves provider key for BYOK models', () => {
            const byokModels = [model('claude-sonnet-4', 'byok-key-1')]
            const keys = [providerKey('byok-key-1', 'anthropic')]
            const result = resolveTraceModelSelection('claude-sonnet-4', 'anthropic', byokModels, keys)
            expect(result.resolvedModelId).toBe('claude-sonnet-4')
            expect(result.providerKeyId).toBe('byok-key-1')
        })

        it('scopes matching to namespace prefix when model has slashes', () => {
            const models = [model('claude-sonnet-4', 'key-a'), model('gpt-5', 'key-b')]
            const result = resolveTraceModelSelection('anthropic/claude-sonnet-4-5-20250929', 'anthropic', models, [])
            expect(result.resolvedModelId).toBe('claude-sonnet-4')
        })

        it('picks deterministic provider key from sorted order', () => {
            const models = [model('claude-sonnet-4', 'key-z'), model('claude-sonnet-4', 'key-a')]
            const keys = [providerKey('key-a', 'anthropic'), providerKey('key-z', 'anthropic')]
            const result = resolveTraceModelSelection('claude-sonnet-4', 'anthropic', models, keys)
            expect(result.providerKeyId).toBe('key-a')
        })
    })
})
