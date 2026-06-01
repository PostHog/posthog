let uuidCounter = 0
Object.defineProperty(globalThis, 'crypto', {
    value: {
        randomUUID: () => `mock-uuid-${String(uuidCounter++).padStart(4, '0')}`,
    },
})

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { llmTaggerLogic } from './llmTaggerLogic'
import { Tagger, TaggerType } from './types'

const mockProviderKeys: LLMProviderKey[] = [
    {
        id: 'key-1',
        provider: 'openai',
        name: 'OpenAI Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-...1234',
        azure_endpoint_display: null,
        api_version_display: null,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
    {
        id: 'key-2',
        provider: 'anthropic',
        name: 'Anthropic Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-ant-...5678',
        azure_endpoint_display: null,
        api_version_display: null,
        created_at: '2024-01-02T00:00:00Z',
        created_by: null,
        last_used_at: null,
    },
]

const mockTagger: Tagger = {
    id: 'tagger-123',
    name: 'Test Tagger',
    description: 'A test tagger',
    enabled: true,
    tagger_type: 'llm' as TaggerType,
    tagger_config: {
        prompt: 'Tag this generation',
        tags: [
            { name: 'billing', description: 'Billing related' },
            { name: 'support', description: 'Support related' },
        ],
        min_tags: 0,
        max_tags: null,
    },
    conditions: [{ id: 'cond-1', rollout_percentage: 50, properties: [] }],
    model_configuration: {
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: 'key-1',
    },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

describe('llmTaggerLogic', () => {
    let logic: ReturnType<typeof llmTaggerLogic.build>
    let keysLogic: ReturnType<typeof llmProviderKeysLogic.build>

    beforeEach(() => {
        uuidCounter = 0
        useMocks({
            get: {
                '/api/environments/:team_id/llm_analytics/provider_keys/': { results: mockProviderKeys },
                '/api/environments/:team_id/taggers/:id/': mockTagger,
            },
            post: {
                '/api/environments/:team_id/query/:kind': { results: [] },
            },
        })
        initKeaTests()
        keysLogic = llmProviderKeysLogic()
        keysLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        keysLogic?.unmount()
    })

    describe('new tagger', () => {
        beforeEach(() => {
            logic = llmTaggerLogic({ id: 'new' })
            logic.mount()
        })

        it('isNewTagger is true', () => {
            expect(logic.values.isNewTagger).toBe(true)
        })

        it('has default form values', () => {
            expect(logic.values.taggerForm).toMatchObject({
                name: '',
                description: '',
                enabled: false,
                tagger_type: 'llm',
                tagger_config: {
                    prompt: '',
                    tags: [{ name: '', description: '' }],
                    min_tags: 0,
                    max_tags: null,
                },
                model_configuration: null,
            })
        })

        it('does not load tagger from API', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadTaggerSuccess'])
        })
    })

    describe('existing tagger', () => {
        beforeEach(() => {
            logic = llmTaggerLogic({ id: 'tagger-123' })
            logic.mount()
        })

        it('isNewTagger is false', () => {
            expect(logic.values.isNewTagger).toBe(false)
        })

        it('loads tagger and populates form', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggerSuccess'])

            expect(logic.values.tagger).toEqual(mockTagger)
            expect(logic.values.taggerForm).toMatchObject({
                name: 'Test Tagger',
                description: 'A test tagger',
                enabled: true,
                tagger_type: 'llm',
                tagger_config: mockTagger.tagger_config,
            })
        })

        it('loads tag runs on mount', async () => {
            await expectLogic(logic).toDispatchActions(['loadTagRuns'])
        })
    })

    describe('reducers', () => {
        beforeEach(() => {
            logic = llmTaggerLogic({ id: 'tagger-123' })
            logic.mount()
        })

        it('selectedModel is set from loaded tagger', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggerSuccess']).toMatchValues({
                selectedModel: 'gpt-5-mini',
            })
        })

        it('selectedPickerProviderKeyId is set from loaded tagger', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggerSuccess']).toMatchValues({
                selectedPickerProviderKeyId: 'key-1',
            })
        })

        it('activeTab defaults to runs', () => {
            expect(logic.values.activeTab).toBe('runs')
        })

        it('setActiveTab updates active tab', async () => {
            logic.actions.setActiveTab('configuration')

            await expectLogic(logic).toMatchValues({ activeTab: 'configuration' })
        })

        it('hogTestResults starts as null', () => {
            expect(logic.values.hogTestResults).toBeNull()
        })

        it('clearHogTestResults resets to null', async () => {
            logic.actions.testHogTaggerSuccess([
                {
                    event_uuid: 'e1',
                    input_preview: 'hello',
                    output_preview: 'world',
                    tags: ['billing'],
                    reasoning: 'matched',
                    error: null,
                },
            ])

            await expectLogic(logic).toMatchValues({
                hogTestResults: expect.arrayContaining([expect.objectContaining({ event_uuid: 'e1' })]),
            })

            logic.actions.clearHogTestResults()

            await expectLogic(logic).toMatchValues({ hogTestResults: null })
        })

        it('hogTestLoading tracks test lifecycle', async () => {
            expect(logic.values.hogTestLoading).toBe(false)

            logic.actions.testHogTagger()

            expect(logic.values.hogTestLoading).toBe(true)

            logic.actions.testHogTaggerSuccess([])

            await expectLogic(logic).toMatchValues({ hogTestLoading: false })
        })
    })

    describe('tag management', () => {
        beforeEach(() => {
            logic = llmTaggerLogic({ id: 'new' })
            logic.mount()
        })

        it('addTag appends an empty tag', async () => {
            logic.actions.addTag()

            await expectLogic(logic).toMatchValues({
                taggerForm: expect.objectContaining({
                    tagger_config: expect.objectContaining({
                        tags: [
                            { name: '', description: '' },
                            { name: '', description: '' },
                        ],
                    }),
                }),
            })
        })

        it('removeTag removes tag at index', async () => {
            logic.actions.addTag()
            logic.actions.updateTag(0, 'name', 'first')
            logic.actions.updateTag(1, 'name', 'second')

            logic.actions.removeTag(0)

            await expectLogic(logic).toMatchValues({
                taggerForm: expect.objectContaining({
                    tagger_config: expect.objectContaining({
                        tags: [{ name: 'second', description: '' }],
                    }),
                }),
            })
        })

        it('updateTag updates name field', async () => {
            logic.actions.updateTag(0, 'name', 'billing')

            await expectLogic(logic).toMatchValues({
                taggerForm: expect.objectContaining({
                    tagger_config: expect.objectContaining({
                        tags: [{ name: 'billing', description: '' }],
                    }),
                }),
            })
        })

        it('updateTag updates description field', async () => {
            logic.actions.updateTag(0, 'description', 'Billing related queries')

            await expectLogic(logic).toMatchValues({
                taggerForm: expect.objectContaining({
                    tagger_config: expect.objectContaining({
                        tags: [{ name: '', description: 'Billing related queries' }],
                    }),
                }),
            })
        })
    })

    describe('condition management', () => {
        beforeEach(() => {
            logic = llmTaggerLogic({ id: 'new' })
            logic.mount()
        })

        it('starts with one default condition', () => {
            expect(logic.values.taggerForm.conditions).toHaveLength(1)
            expect(logic.values.taggerForm.conditions[0]).toMatchObject({
                rollout_percentage: 100,
                properties: [],
            })
        })

        it('addCondition appends a new condition', async () => {
            logic.actions.addCondition()

            expect(logic.values.taggerForm.conditions).toHaveLength(2)
            expect(logic.values.taggerForm.conditions[1]).toMatchObject({
                rollout_percentage: 100,
                properties: [],
            })
        })

        it('removeCondition removes condition at index', async () => {
            logic.actions.addCondition()

            expect(logic.values.taggerForm.conditions).toHaveLength(2)
            const secondCondition = logic.values.taggerForm.conditions[1]

            logic.actions.removeCondition(0)

            expect(logic.values.taggerForm.conditions).toHaveLength(1)
            expect(logic.values.taggerForm.conditions[0].id).toBe(secondCondition.id)
        })

        it('setConditions replaces all conditions', async () => {
            const newConditions = [
                { id: 'custom-1', rollout_percentage: 25, properties: [] },
                { id: 'custom-2', rollout_percentage: 75, properties: [] },
            ]
            logic.actions.setConditions(newConditions)

            await expectLogic(logic).toMatchValues({
                taggerForm: expect.objectContaining({
                    conditions: newConditions,
                }),
            })
        })
    })

    describe('form validation', () => {
        const submitAndGetErrors = async (): Promise<any> => {
            try {
                await expectLogic(logic, () => {
                    logic.actions.submitTaggerForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }
            return (logic.values as any).taggerFormErrors
        }

        describe('LLM tagger', () => {
            beforeEach(() => {
                logic = llmTaggerLogic({ id: 'new' })
                logic.mount()
            })

            it('requires name', async () => {
                const errors = await submitAndGetErrors()
                expect(errors.name).toBe('Name is required')
            })

            it('requires prompt', async () => {
                const errors = await submitAndGetErrors()
                expect(errors.tagger_config.prompt).toBe('Prompt is required')
            })

            it('reports error when tag name is empty', async () => {
                const errors = await submitAndGetErrors()
                expect(errors.tagger_config.tags).toEqual([{ name: 'All tags must have a name' }])
            })

            it('reports error when no tags exist', async () => {
                logic.actions.removeTag(0)
                const errors = await submitAndGetErrors()
                expect(errors.tagger_config.tags).toEqual([{ name: 'At least one tag is required' }])
            })

            it('clears errors with valid form', async () => {
                logic.actions.setTaggerFormValues({
                    name: 'Valid Tagger',
                    tagger_config: {
                        prompt: 'Tag this',
                        tags: [{ name: 'test', description: '' }],
                        min_tags: 0,
                        max_tags: null,
                    },
                })

                const errors = await submitAndGetErrors()
                expect(errors.name).toBeUndefined()
                expect(errors.tagger_config.prompt).toBeUndefined()
                expect(errors.tagger_config.tags).toBeUndefined()
            })
        })

        describe('Hog tagger', () => {
            beforeEach(() => {
                logic = llmTaggerLogic({ id: 'new' })
                logic.mount()
                logic.actions.setTaggerFormValues({ tagger_type: 'hog' })
            })

            it('requires source code', async () => {
                logic.actions.setTaggerFormValues({
                    tagger_config: { source: '', tags: [] },
                })
                const errors = await submitAndGetErrors()
                expect(errors.tagger_config.source).toBe('Hog source code is required')
            })

            it('does not require prompt or tags', async () => {
                logic.actions.setTaggerFormValues({
                    name: 'Hog Tagger',
                    tagger_config: { source: 'return []', tags: [] },
                })
                const errors = await submitAndGetErrors()
                expect(errors.name).toBeUndefined()
                expect(errors.tagger_config.source).toBeUndefined()
                expect(errors.tagger_config).not.toHaveProperty('prompt')
                expect(errors.tagger_config).not.toHaveProperty('tags')
            })
        })
    })

    describe('selectModelFromPicker', () => {
        beforeEach(() => {
            logic = llmTaggerLogic({ id: 'new' })
            logic.mount()
        })

        it('sets model configuration from BYOK provider key', async () => {
            await expectLogic(keysLogic).toDispatchActions(['loadProviderKeysSuccess'])

            logic.actions.selectModelFromPicker('gpt-5', 'key-1')

            await expectLogic(logic).toMatchValues({
                selectedModel: 'gpt-5',
                taggerForm: expect.objectContaining({
                    model_configuration: {
                        provider: 'openai',
                        model: 'gpt-5',
                        provider_key_id: 'key-1',
                    },
                }),
            })
        })

        it('sets model configuration from trial provider key', async () => {
            logic.actions.selectModelFromPicker('gpt-5', 'trial:openai')

            await expectLogic(logic).toMatchValues({
                selectedModel: 'gpt-5',
                taggerForm: expect.objectContaining({
                    model_configuration: {
                        provider: 'openai',
                        model: 'gpt-5',
                        provider_key_id: null,
                    },
                }),
            })
        })

        it('ignores empty modelId', async () => {
            logic.actions.selectModelFromPicker('', 'key-1')

            await expectLogic(logic).toMatchValues({
                selectedModel: '',
                taggerForm: expect.objectContaining({
                    model_configuration: null,
                }),
            })
        })
    })

    describe('loadTagRuns', () => {
        it('returns empty for new tagger', async () => {
            logic = llmTaggerLogic({ id: 'new' })
            logic.mount()

            logic.actions.loadTagRuns()

            await expectLogic(logic).toDispatchActions(['loadTagRunsSuccess']).toMatchValues({
                tagRuns: [],
            })
        })

        it('parses query results into TagRun objects', async () => {
            logic = llmTaggerLogic({ id: 'tagger-123' })
            logic.mount()

            // Wait for initial load (returns empty from default mock)
            await expectLogic(logic).toDispatchActions(['loadTagRunsSuccess'])

            // Now override the query mock and reload
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': {
                        results: [
                            [
                                '2024-01-01T12:00:00Z',
                                '["billing","support"]',
                                'Found billing keyword',
                                'trace-1',
                                'event-1',
                                'tagger-123',
                                'Test Tagger',
                            ],
                        ],
                    },
                },
            })

            logic.actions.loadTagRuns()

            await expectLogic(logic)
                .toDispatchActions(['loadTagRunsSuccess'])
                .toMatchValues({
                    tagRuns: [
                        {
                            timestamp: '2024-01-01T12:00:00Z',
                            tags: ['billing', 'support'],
                            reasoning: 'Found billing keyword',
                            trace_id: 'trace-1',
                            target_event_id: 'event-1',
                            tagger_id: 'tagger-123',
                            tagger_name: 'Test Tagger',
                        },
                    ],
                })
        })
    })
})
