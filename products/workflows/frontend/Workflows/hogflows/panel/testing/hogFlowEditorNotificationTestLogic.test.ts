import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInvocationGlobals } from '~/types'

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
        // Clear localStorage to prevent state leakage between tests
        localStorage.clear()

        resetContext({
            plugins: [testUtilsPlugin],
        })

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
                '/api/environments/@current/messaging_categories': [],
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

    describe('emailAddressOverride reducer', () => {
        it('should only be set manually, not automatically', async () => {
            const globalsWithEmail: CyclotronJobInvocationGlobals = {
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
                    properties: { email: 'new@example.com' },
                    name: 'Test Person',
                    url: '',
                },
                groups: {},
                project: { id: 1, name: 'Test', url: '' },
                source: { name: 'Test', url: '' },
            }

            // Loading a person should NOT automatically set emailAddressOverride
            await expectLogic(logic, () => {
                logic.actions.loadSamplePersonByDistinctIdSuccess(globalsWithEmail)
            }).toMatchValues({
                emailAddressOverride: null, // Should remain null, not automatically set
            })

            // Only manual setting should update it
            await expectLogic(logic, () => {
                logic.actions.setEmailAddressOverride('manual@example.com')
            }).toMatchValues({
                emailAddressOverride: 'manual@example.com',
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

        it('should reload person when sampleGlobals is null or does not match selectedPersonDistinctId', async () => {
            const distinctId1 = 'person-1-id'
            const distinctId2 = 'person-2-id'
            const globalsForPerson1 = createGlobals(distinctId1)

            // Reload when sampleGlobals is null
            await expectLogic(logic, () => {
                logic.actions.setSelectedPersonDistinctId(distinctId1)
            }).toMatchValues({
                selectedPersonDistinctId: distinctId1,
                sampleGlobals: null,
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/persons/': {
                        results: [
                            {
                                id: 'person-1',
                                distinct_ids: [distinctId1],
                                properties: { email: 'person1@example.com' },
                            },
                        ],
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersons()
            }).toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess', 'loadSamplePersonByDistinctId'])

            // Reload when sampleGlobals doesn't match selectedPersonDistinctId
            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(JSON.stringify(globalsForPerson1, null, 2))
                logic.actions.setSelectedPersonDistinctId(distinctId2)
            }).toMatchValues({
                sampleGlobals: globalsForPerson1,
                selectedPersonDistinctId: distinctId2,
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/persons/': {
                        results: [
                            {
                                id: 'person-2',
                                distinct_ids: [distinctId2],
                                properties: { email: 'person2@example.com' },
                            },
                        ],
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersons()
            }).toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess', 'loadSamplePersonByDistinctId'])
        })

        it('should not reload person if sampleGlobals matches selectedPersonDistinctId', async () => {
            const distinctId = 'person-1-id'
            const globalsForPerson1 = createGlobals(distinctId)

            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(JSON.stringify(globalsForPerson1, null, 2))
                logic.actions.setSelectedPersonDistinctId(distinctId)
            }).toMatchValues({
                sampleGlobals: globalsForPerson1,
                selectedPersonDistinctId: distinctId,
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/persons/': {
                        results: [
                            {
                                id: 'person-1',
                                distinct_ids: [distinctId],
                                properties: { email: 'person1@example.com' },
                            },
                        ],
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersons()
            })
                .toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess'])
                .toNotHaveDispatchedActions(['loadSamplePersonByDistinctId'])
                .toMatchValues({
                    selectedPersonDistinctId: distinctId,
                    sampleGlobals: globalsForPerson1,
                })
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
})
