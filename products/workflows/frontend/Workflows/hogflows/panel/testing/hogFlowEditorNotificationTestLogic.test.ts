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

        it('should preserve state when JSON is invalid', async () => {
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

            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals('invalid json {')
            }).toMatchValues({
                sampleGlobals: initialGlobals,
            })
        })

        it('should preserve state when globals is null', async () => {
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

            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(null)
            }).toMatchValues({
                sampleGlobals: initialGlobals,
            })
        })
    })

    describe('emailAddressOverride reducer', () => {
        it('should update email override when person changes', async () => {
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

            await expectLogic(logic, () => {
                logic.actions.loadSamplePersonByDistinctIdSuccess(globalsWithEmail)
            }).toMatchValues({
                emailAddressOverride: 'new@example.com',
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
                    emailAddressOverride: 'test@example.com',
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
})
