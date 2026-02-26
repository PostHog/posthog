import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { byokModelPickerLogic } from './byokModelPickerLogic'

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

describe('byokModelPickerLogic', () => {
    let logic: ReturnType<typeof byokModelPickerLogic.build>

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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
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

            logic = byokModelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const groups = logic.values.providerModelGroups
            expect(groups).toHaveLength(2)

            const labels = groups.map((g) => g.label).sort()
            expect(labels).toEqual(['OpenAI (Production)', 'OpenAI (Staging)'])
        })
    })

    describe('selectedProviderForModel', () => {
        it('should return the provider for a matching model and key', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', name: 'Key', state: 'ok' },
                            { id: 'key-2', provider: 'anthropic', name: 'Key', state: 'ok' },
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

            logic = byokModelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.selectedProviderForModel('gpt-4.1', 'key-1')).toBe('openai')
            expect(logic.values.selectedProviderForModel('claude-sonnet-4', 'key-2')).toBe('anthropic')
            expect(logic.values.selectedProviderForModel('nonexistent', 'key-1')).toBeNull()
            expect(logic.values.selectedProviderForModel('gpt-4.1', 'wrong-key')).toBeNull()
        })
    })

    describe('filteredProviderModelGroups', () => {
        it('should filter models by search string matching name or id', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', name: 'Key', state: 'ok' }],
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

            logic = byokModelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSearch('gpt-5')

            const filtered = logic.values.filteredProviderModelGroups
            expect(filtered).toHaveLength(1)
            expect(filtered[0].models).toHaveLength(1)
            expect(filtered[0].models[0].id).toBe('gpt-5')
        })

        it('should return all groups when search is empty', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [{ id: 'key-1', provider: 'openai', name: 'Key', state: 'ok' }],
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

            logic = byokModelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filteredProviderModelGroups).toEqual(logic.values.providerModelGroups)
        })

        it('should hide disabled groups during search', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', name: 'OpenAI Key', state: 'ok' },
                            { id: 'key-2', provider: 'anthropic', name: 'Anthropic Key', state: 'error' },
                        ],
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

            logic = byokModelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // Without search, disabled group should be present
            const allGroups = logic.values.filteredProviderModelGroups
            expect(allGroups.some((g) => g.disabled)).toBe(true)

            // With search, disabled group should be hidden
            logic.actions.setSearch('gpt')
            const filtered = logic.values.filteredProviderModelGroups
            expect(filtered.every((g) => !g.disabled)).toBe(true)
            expect(filtered).toHaveLength(1)
            expect(filtered[0].provider).toBe('openai')
        })

        it('should exclude groups with no matching models', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': {
                        results: [
                            { id: 'key-1', provider: 'openai', name: 'OpenAI Key', state: 'ok' },
                            { id: 'key-2', provider: 'anthropic', name: 'Anthropic Key', state: 'ok' },
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

            logic = byokModelPickerLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSearch('claude')

            const filtered = logic.values.filteredProviderModelGroups
            expect(filtered).toHaveLength(1)
            expect(filtered[0].provider).toBe('anthropic')
        })
    })
})
