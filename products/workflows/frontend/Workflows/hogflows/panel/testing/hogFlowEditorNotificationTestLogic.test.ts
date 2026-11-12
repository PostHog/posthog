import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInvocationGlobals, PersonType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorNotificationTestLogic } from './hogFlowEditorNotificationTestLogic'

jest.mock('~/queries/query', () => {
    const actual = jest.requireActual('~/queries/query')
    return {
        ...actual,
        performQuery: jest.fn().mockResolvedValue({ results: [] }),
    }
})

describe('hogFlowEditorNotificationTestLogic', () => {
    let logic: ReturnType<typeof hogFlowEditorNotificationTestLogic.build>
    let workflowLogicInstance: ReturnType<typeof workflowLogic.build>

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()

        useMocks({
            get: {
                '/api/environments/:team_id/persons/': { results: [] },
                '/api/environments/@current/hog_flows/test-workflow-id/': {
                    id: 'test-workflow-id',
                    team_id: 1,
                    name: 'Test Workflow',
                    status: 'draft',
                    actions: [],
                    edges: [],
                },
                '/api/environments/@current/messaging_categories': { results: [] },
            },
        })

        initKeaTests()

        workflowLogicInstance = workflowLogic({ id: 'test-workflow-id' })
        workflowLogicInstance.mount()

        logic = hogFlowEditorNotificationTestLogic({ id: 'test-workflow-id' })
        logic.mount()
    })

    describe('setSampleGlobals reducer', () => {
        it('should parse valid JSON and update sampleGlobals', async () => {
            const validGlobals: CyclotronJobInvocationGlobals = {
                event: {
                    uuid: 'test-uuid',
                    distinct_id: 'test-distinct-id',
                    timestamp: '2024-01-01T00:00:00Z',
                    elements_chain: '',
                    url: '',
                    event: '$pageview',
                    properties: {},
                },
                person: {
                    id: 'person-1',
                    properties: { email: 'test@example.com' },
                    name: 'Test Person',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(JSON.stringify(validGlobals, null, 2))
            }).toMatchValues({
                sampleGlobals: validGlobals,
            })
        })

        it('should preserve state when JSON is invalid or null', async () => {
            const initialGlobals: CyclotronJobInvocationGlobals = {
                event: {
                    uuid: 'test-uuid',
                    distinct_id: 'test-distinct-id',
                    timestamp: '2024-01-01T00:00:00Z',
                    elements_chain: '',
                    url: '',
                    event: '$pageview',
                    properties: {},
                },
                person: {
                    id: 'person-1',
                    properties: {},
                    name: 'Test Person',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(JSON.stringify(initialGlobals, null, 2))
            }).toMatchValues({
                sampleGlobals: initialGlobals,
            })

            // Test invalid JSON
            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals('invalid json {')
            }).toMatchValues({
                sampleGlobals: initialGlobals,
            })

            // Test null
            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(null)
            }).toMatchValues({
                sampleGlobals: initialGlobals,
            })
        })
    })

    describe('loadSamplePersonByDistinctIdSuccess listener', () => {
        it('should reorder globals with person first', async () => {
            const globals: CyclotronJobInvocationGlobals = {
                event: {
                    uuid: 'test-uuid',
                    distinct_id: 'test-distinct-id',
                    timestamp: '2024-01-01T00:00:00Z',
                    elements_chain: '',
                    url: '',
                    event: '$pageview',
                    properties: {},
                },
                person: {
                    id: 'person-1',
                    properties: { email: 'test@example.com' },
                    name: 'Test Person',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersonByDistinctIdSuccess(globals)
            })
                .toDispatchActions(['setSampleGlobals'])
                .toMatchValues({
                    sampleGlobals: globals,
                    emailAddressOverride: null, // Should not be automatically set
                })

            // Verify that the form was updated with reordered globals
            const formValue = logic.values.testInvocation?.globals
            expect(formValue).toBeTruthy()
            if (formValue) {
                const parsed = JSON.parse(formValue)
                const keys = Object.keys(parsed)
                expect(keys[0]).toBe('person')
                expect(keys[1]).toBe('event')
            }
        })
    })

    describe('email override behavior when switching persons', () => {
        it('should not automatically set email override and preserve manual overrides', async () => {
            const person1Globals: CyclotronJobInvocationGlobals = {
                event: {
                    uuid: 'test-uuid-1',
                    distinct_id: 'person-1-id',
                    timestamp: '2024-01-01T00:00:00Z',
                    elements_chain: '',
                    url: '',
                    event: '$pageview',
                    properties: {},
                },
                person: {
                    id: 'person-1',
                    properties: { email: 'person1@example.com' },
                    name: 'Person 1',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            const person2Globals: CyclotronJobInvocationGlobals = {
                event: {
                    uuid: 'test-uuid-2',
                    distinct_id: 'person-2-id',
                    timestamp: '2024-01-01T00:00:00Z',
                    elements_chain: '',
                    url: '',
                    event: '$pageview',
                    properties: {},
                },
                person: {
                    id: 'person-2',
                    properties: { email: 'person2@example.com' },
                    name: 'Person 2',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            // Test 1: No manual override - should remain null when switching persons
            await expectLogic(logic, () => {
                logic.actions.loadSamplePersonByDistinctIdSuccess(person1Globals)
            }).toMatchValues({
                emailAddressOverride: null,
            })

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersonByDistinctIdSuccess(person2Globals)
            }).toMatchValues({
                emailAddressOverride: null,
            })

            // Test 2: Manual override - should be preserved when switching persons
            await expectLogic(logic, () => {
                logic.actions.setEmailAddressOverride('manual-override@example.com')
            }).toMatchValues({
                emailAddressOverride: 'manual-override@example.com',
            })

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersonByDistinctIdSuccess(person1Globals)
            }).toMatchValues({
                emailAddressOverride: 'manual-override@example.com', // Preserved
            })
        })
    })

    describe('loadSamplePersonsSuccess reload logic', () => {
        const createGlobals = (distinctId: string): CyclotronJobInvocationGlobals => ({
            event: {
                uuid: `test-uuid-${distinctId}`,
                distinct_id: distinctId,
                timestamp: '2024-01-01T00:00:00Z',
                elements_chain: '',
                url: '',
                event: '$pageview',
                properties: {},
            },
            person: {
                id: `person-${distinctId}`,
                properties: { email: `${distinctId}@example.com` },
                name: `Person ${distinctId}`,
                url: '',
            },
            groups: {},
            project: { id: 1, name: 'Test', url: '' },
            source: { name: 'Test', url: '' },
        })

        const person1: PersonType = {
            id: 'person-1',
            uuid: 'person-1',
            name: 'Person 1',
            distinct_ids: ['person-1-id'],
            properties: { email: 'person1@example.com' },
        }
        const person2: PersonType = {
            id: 'person-2',
            uuid: 'person-2',
            name: 'Person 2',
            distinct_ids: ['person-2-id'],
            properties: { email: 'person2@example.com' },
        }

        const loadSamplePersons = async (): Promise<void> => {
            await expectLogic(logic, () => {
                logic.actions.loadSamplePersons()
            }).toFinishAllListeners()
        }

        beforeEach(async () => {
            await expectLogic(logic).toFinishAllListeners()
            const persons = [person1, person2]
            useMocks({
                get: {
                    '/api/environments/:team_id/persons/': ({ request }) => {
                        const url = new URL(request.url)
                        const distinctId = url.searchParams.get('distinct_id')
                        const limit = Number(url.searchParams.get('limit') ?? persons.length)
                        const matching = distinctId
                            ? persons.filter((person) => person.distinct_ids.includes(distinctId))
                            : persons
                        return [200, { results: matching.slice(0, limit) }]
                    },
                },
            })
        })

        it.each([
            ['no sample globals are stored', null],
            ['the stored sample globals belong to another person', createGlobals('person-1-id')],
        ])('loads the selected person when %s', async (_, storedGlobals) => {
            if (storedGlobals) {
                logic.actions.setSampleGlobals(JSON.stringify(storedGlobals))
            }
            logic.actions.setSelectedPersonDistinctId('person-2-id')

            await loadSamplePersons()

            expect(logic.values).toMatchObject({
                selectedPersonDistinctId: 'person-2-id',
                sampleGlobalsLoading: false,
                sampleGlobals: {
                    event: { distinct_id: 'person-2-id' },
                    person: { id: 'person-2', name: 'Person 2', properties: { email: 'person2@example.com' } },
                },
            })
        })

        it('keeps the stored sample globals when they belong to the selected person', async () => {
            const storedGlobals = createGlobals('person-1-id')
            logic.actions.setSampleGlobals(JSON.stringify(storedGlobals))
            logic.actions.setSelectedPersonDistinctId('person-1-id')

            await loadSamplePersons()

            expect(logic.values.sampleGlobals).toEqual(storedGlobals)
        })
    })

    describe('persistence', () => {
        it('should persist emailAddressOverride, selectedPersonDistinctId, and sampleGlobals across unmount/remount', async () => {
            const testDistinctId = 'test-distinct-id-123'
            const testEmail = 'custom@example.com'
            const testGlobals: CyclotronJobInvocationGlobals = {
                event: {
                    uuid: 'test-uuid',
                    distinct_id: testDistinctId,
                    timestamp: '2024-01-01T00:00:00Z',
                    elements_chain: '',
                    url: '',
                    event: '$pageview',
                    properties: {},
                },
                person: {
                    id: 'person-1',
                    properties: { email: testEmail },
                    name: 'Test Person',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            await expectLogic(logic, () => {
                logic.actions.setSelectedPersonDistinctId(testDistinctId)
                logic.actions.setEmailAddressOverride(testEmail)
                logic.actions.setSampleGlobals(JSON.stringify(testGlobals, null, 2))
            }).toMatchValues({
                selectedPersonDistinctId: testDistinctId,
                emailAddressOverride: testEmail,
                sampleGlobals: testGlobals,
            })

            logic.unmount()

            const newLogic = hogFlowEditorNotificationTestLogic({ id: 'test-workflow-id' })
            newLogic.mount()

            await expectLogic(newLogic).toMatchValues({
                selectedPersonDistinctId: testDistinctId,
                emailAddressOverride: testEmail,
                sampleGlobals: testGlobals,
            })

            newLogic.unmount()
        })
    })

    describe('next step after a test run', () => {
        it.each([
            ['an unmet wait returns the selected step', 'wait_step', null],
            ['a skipped run returns no step', null, null],
            ['the response leaves out the next step', undefined, null],
            ['the run moves on', 'step_c', 'step_c'],
        ])('when %s', async (_, returnedStepId, expectedNextActionId) => {
            useMocks({
                post: {
                    '/api/environments/:team_id/hog_flows/:id/invocations': async ({ request }) => {
                        const { current_action_id } = (await request.json()) as { current_action_id: string }
                        const nextActionId = current_action_id === 'step_a' ? 'wait_step' : returnedStepId
                        return [200, { status: 'success', logs: [], nextActionId }]
                    },
                },
            })
            logic.actions.setTestInvocationValue('globals', '{}')

            const runTestOn = async (stepId: string): Promise<void> => {
                logic.actions.setSelectedNodeId(stepId)
                await expectLogic(logic, () => logic.actions.submitTestInvocation()).toDispatchActions([
                    'submitTestInvocationSuccess',
                ])
            }

            await runTestOn('step_a')
            expect(logic.values.nextActionId).toBe('wait_step')
            await runTestOn('wait_step')
            expect(logic.values.nextActionId).toBe(expectedNextActionId)
        })
    })
})
