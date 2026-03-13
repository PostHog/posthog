import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { filterGroups, findSelectedProvider, parseTrialProviderKeyId } from './ModelPicker'
import {
    buildTrialProviderModelGroups,
    modelPickerLogic,
    type ModelOption,
    type ProviderModelGroup,
} from './modelPickerLogic'

// API responses use snake_case is_recommended
const BYOK_OPENAI_MODELS = [
    { id: 'gpt-4.1', name: 'GPT-4.1', provider: 'OpenAI', description: '', is_recommended: true },
    { id: 'gpt-5', name: 'GPT-5', provider: 'OpenAI', description: '', is_recommended: true },
]

const BYOK_OPENAI_MODELS_MIXED = [
    { id: 'gpt-4.1', name: 'GPT-4.1', provider: 'OpenAI', description: '', is_recommended: true },
    { id: 'gpt-5', name: 'GPT-5', provider: 'OpenAI', description: '', is_recommended: true },
    {
        id: 'gpt-4o-audio-preview',
        name: 'gpt-4o-audio-preview',
        provider: 'OpenAI',
        description: '',
        is_recommended: false,
    },
]

const BYOK_ANTHROPIC_MODELS = [
    { id: 'claude-sonnet-4', name: 'Claude Sonnet 4', provider: 'Anthropic', description: '', is_recommended: true },
]

describe('modelPickerLogic', () => {
    let logic: ReturnType<typeof modelPickerLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('loadByokModels', () => {
        it('should load and attach providerKeyId to models from valid keys', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', state: 'ok' }],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'key-1') {
                            return [200, BYOK_OPENAI_MODELS]
                        }
                        return [200, []]
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.byokModels).toEqual(
                BYOK_OPENAI_MODELS.map((m) => ({
                    id: m.id,
                    name: m.name,
                    provider: m.provider,
                    description: m.description,
                    isRecommended: true,
                    providerKeyId: 'key-1',
                }))
            )
        })

        it('should map is_recommended correctly for both true and false values', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', state: 'ok' }],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        if (req.url.searchParams.get('provider_key_id') === 'key-1') {
                            return [200, BYOK_OPENAI_MODELS_MIXED]
                        }
                        return [200, []]
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const models = logic.values.byokModels
            expect(models).toHaveLength(3)

            const recommended = models.filter((m) => m.isRecommended)
            const nonRecommended = models.filter((m) => !m.isRecommended)
            expect(recommended).toHaveLength(2)
            expect(nonRecommended).toHaveLength(1)
            expect(nonRecommended[0].id).toBe('gpt-4o-audio-preview')
        })

        it('should return empty array when no valid keys exist', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', state: 'invalid' }],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.byokModels).toEqual([])
        })

        it('should deduplicate models by providerKeyId and model id', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', state: 'ok' },
                            { id: 'key-2', provider: 'anthropic', state: 'ok' },
                        ],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        const keyId = req.url.searchParams.get('provider_key_id')
                        if (keyId === 'key-1') {
                            return [200, BYOK_OPENAI_MODELS]
                        }
                        if (keyId === 'key-2') {
                            return [200, BYOK_ANTHROPIC_MODELS]
                        }
                        return [200, []]
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const openaiModels = logic.values.byokModels.filter((m) => m.providerKeyId === 'key-1')
            const anthropicModels = logic.values.byokModels.filter((m) => m.providerKeyId === 'key-2')
            expect(openaiModels).toHaveLength(2)
            expect(anthropicModels).toHaveLength(1)
        })

        it('should gracefully handle API errors for individual keys', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', state: 'ok' },
                            { id: 'key-2', provider: 'anthropic', state: 'ok' },
                        ],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        const keyId = req.url.searchParams.get('provider_key_id')
                        if (keyId === 'key-1') {
                            return [500, { error: 'Internal error' }]
                        }
                        if (keyId === 'key-2') {
                            return [200, BYOK_ANTHROPIC_MODELS]
                        }
                        return [200, []]
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // key-1 failed, but key-2 models should still be present
            expect(logic.values.byokModels).toEqual(
                BYOK_ANTHROPIC_MODELS.map((m) => ({
                    id: m.id,
                    name: m.name,
                    provider: m.provider,
                    description: m.description,
                    isRecommended: true,
                    providerKeyId: 'key-2',
                }))
            )
        })
    })

    describe('hasByokKeys', () => {
        it('should return true when at least one key has ok state', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', state: 'invalid' },
                            { id: 'key-2', provider: 'anthropic', state: 'ok' },
                        ],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': () => [200, []],
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.hasByokKeys).toBe(true)
        })

        it('should return false when all keys are non-ok', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', state: 'invalid' },
                            { id: 'key-2', provider: 'anthropic', state: 'error' },
                        ],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.hasByokKeys).toBe(false)
        })

        it('should return false when no keys exist', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.hasByokKeys).toBe(false)
        })
    })

    describe('providerModelGroups', () => {
        it('should group models by provider key', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', name: 'My OpenAI Key', state: 'ok' },
                            { id: 'key-2', provider: 'anthropic', name: 'My Anthropic Key', state: 'ok' },
                        ],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        const keyId = req.url.searchParams.get('provider_key_id')
                        if (keyId === 'key-1') {
                            return [200, BYOK_OPENAI_MODELS]
                        }
                        if (keyId === 'key-2') {
                            return [200, BYOK_ANTHROPIC_MODELS]
                        }
                        return [200, []]
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const groups = logic.values.providerModelGroups
            expect(groups).toHaveLength(2)

            const labels = groups.map((g) => g.label).sort()
            expect(labels).toEqual(['Anthropic', 'OpenAI'])

            const openaiGroup = groups.find((g) => g.provider === 'openai')
            expect(openaiGroup?.models).toHaveLength(2)
            expect(openaiGroup?.providerKeyId).toBe('key-1')
        })

        it('should disambiguate labels when multiple keys exist for same provider', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', name: 'Production', state: 'ok' },
                            { id: 'key-2', provider: 'openai', name: 'Staging', state: 'ok' },
                        ],
                    },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': {
                        active_provider_key: null,
                    },
                    '/api/llm_proxy/models/': (req: any) => {
                        const keyId = req.url.searchParams.get('provider_key_id')
                        if (keyId === 'key-1' || keyId === 'key-2') {
                            return [200, BYOK_OPENAI_MODELS]
                        }
                        return [200, []]
                    },
                },
            })

            logic = modelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const groups = logic.values.providerModelGroups
            expect(groups).toHaveLength(2)

            const labels = groups.map((g) => g.label).sort()
            expect(labels).toEqual(['OpenAI (Production)', 'OpenAI (Staging)'])
        })
    })
})

const MODEL_A: ModelOption = { id: 'gpt-5', name: 'GPT-5', provider: 'OpenAI', description: '' }
const MODEL_B: ModelOption = { id: 'claude-sonnet-4', name: 'Claude Sonnet 4', provider: 'Anthropic', description: '' }
const MODEL_C: ModelOption = {
    id: 'gpt-4.1',
    name: 'GPT-4.1',
    provider: 'OpenAI',
    description: '',
    isRecommended: true,
}

const GROUPS: ProviderModelGroup[] = [
    { provider: 'openai', providerKeyId: 'key-1', label: 'OpenAI', models: [MODEL_A, MODEL_C] },
    { provider: 'anthropic', providerKeyId: 'key-2', label: 'Anthropic', models: [MODEL_B] },
]

describe('parseTrialProviderKeyId', () => {
    it.each([
        ['trial:openai', 'openai'],
        ['trial:anthropic', 'anthropic'],
        ['key-123', null],
        ['', null],
        ['trial:', null],
    ])('parseTrialProviderKeyId(%s) => %s', (input, expected) => {
        expect(parseTrialProviderKeyId(input)).toBe(expected)
    })
})

describe('findSelectedProvider', () => {
    it.each([
        ['exact match by providerKeyId and model', 'gpt-5', 'key-1', 'openai'],
        ['fallback to model-only match when providerKeyId is null', 'claude-sonnet-4', null, 'anthropic'],
        ['returns null when model not found', 'unknown-model', 'key-1', null],
        ['returns null for empty groups', 'gpt-5', 'key-1', null],
    ] as const)('%s', (_, model, providerKeyId, expected) => {
        const groups = expected === null && model === 'gpt-5' ? [] : GROUPS
        expect(findSelectedProvider(groups as ProviderModelGroup[], model, providerKeyId)).toBe(expected)
    })
})

describe('filterGroups', () => {
    it('returns all groups when search is empty', () => {
        expect(filterGroups(GROUPS, '')).toBe(GROUPS)
    })

    it('filters models by name (case-insensitive)', () => {
        const result = filterGroups(GROUPS, 'claude')
        expect(result).toHaveLength(1)
        expect(result[0].provider).toBe('anthropic')
    })

    it('filters models by id', () => {
        const result = filterGroups(GROUPS, 'gpt-4.1')
        expect(result).toHaveLength(1)
        expect(result[0].models).toHaveLength(1)
        expect(result[0].models[0].id).toBe('gpt-4.1')
    })

    it('removes groups with no matching models', () => {
        expect(filterGroups(GROUPS, 'nonexistent')).toHaveLength(0)
    })
})

describe('buildTrialProviderModelGroups', () => {
    it('groups models by provider with trial: prefix keys', () => {
        const models: ModelOption[] = [MODEL_A, MODEL_C, MODEL_B]
        const groups = buildTrialProviderModelGroups(models)

        expect(groups).toHaveLength(2)
        expect(groups[0].provider).toBe('openai')
        expect(groups[0].providerKeyId).toBe('trial:openai')
        expect(groups[0].models).toHaveLength(2)
        expect(groups[1].provider).toBe('anthropic')
        expect(groups[1].providerKeyId).toBe('trial:anthropic')
        expect(groups[1].models).toHaveLength(1)
    })

    it('returns empty array for empty input', () => {
        expect(buildTrialProviderModelGroups([])).toEqual([])
    })

    it('sorts groups by provider order', () => {
        const models: ModelOption[] = [
            { ...MODEL_B, provider: 'Anthropic' },
            { ...MODEL_A, provider: 'OpenAI' },
        ]
        const groups = buildTrialProviderModelGroups(models)
        expect(groups.map((g) => g.provider)).toEqual(['openai', 'anthropic'])
    })
})
