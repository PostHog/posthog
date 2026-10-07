import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInvocationGlobals } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlowAction } from '../../types'
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
                '/api/projects/:team_id/persons/': { results: [] },
                '/api/projects/:team_id/hog_flows/test-workflow-id/': {
                    id: 'test-workflow-id',
                    team_id: 1,
                    name: 'Test Workflow',
                    status: 'draft',
                    actions: [],
                    edges: [],
                },
                '/api/projects/:team_id/messaging_categories': { results: [] },
            },
        })

        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags(['workflows-testing-v2'], { 'workflows-testing-v2': true })

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

            // Wait for afterMount's loadSamplePersons to complete before proceeding
            await expectLogic(logic)
                .toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess'])
                .toFinishAllListeners()

            // Reload when sampleGlobals is null
            await expectLogic(logic, () => {
                logic.actions.setSelectedPersonDistinctId(distinctId1)
            }).toMatchValues({
                selectedPersonDistinctId: distinctId1,
                sampleGlobals: null,
            })

            useMocks({
                get: {
                    '/api/projects/:team_id/persons/': {
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
            })
                .toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess', 'loadSamplePersonByDistinctId'])
                .toFinishAllListeners()

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
                    '/api/projects/:team_id/persons/': {
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
            })
                .toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess', 'loadSamplePersonByDistinctId'])
                .toFinishAllListeners()
        })

        it('should not reload person if sampleGlobals matches selectedPersonDistinctId', async () => {
            const distinctId = 'person-1-id'
            const globalsForPerson1 = createGlobals(distinctId)

            // Wait for afterMount's loadSamplePersons to complete before proceeding
            await expectLogic(logic)
                .toDispatchActions(['loadSamplePersons', 'loadSamplePersonsSuccess'])
                .toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setSampleGlobals(JSON.stringify(globalsForPerson1, null, 2))
                logic.actions.setSelectedPersonDistinctId(distinctId)
            }).toMatchValues({
                sampleGlobals: globalsForPerson1,
                selectedPersonDistinctId: distinctId,
            })

            useMocks({
                get: {
                    '/api/projects/:team_id/persons/': {
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
                .toFinishAllListeners()
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

    describe('test email recipient', () => {
        const emailAction = (id: string): HogFlowAction => ({
            id,
            type: 'function_email',
            name: id,
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: '{{ person.properties.email }}', name: '{{ person.properties.name }}' },
                            cc: 'account-manager@example.com',
                            bcc: 'audit@example.com',
                            subject: 'Welcome',
                        },
                    },
                },
            },
        })
        let postedBody: Record<string, any> | null = null

        beforeEach(async () => {
            await expectLogic(workflowLogicInstance).toDispatchActions(['loadWorkflowSuccess'])
            postedBody = null
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/:id/invocations': async ({ request }) => {
                        postedBody = (await request.json()) as Record<string, any>
                        return [200, { status: 'success', nextActionId: null, logs: [] }]
                    },
                },
            })
            workflowLogicInstance.actions.setWorkflowValue('actions', [
                emailAction('welcome_email'),
                emailAction('follow_up_email'),
            ])
            logic.actions.setSampleGlobals(
                JSON.stringify({
                    event: { uuid: 'e1', distinct_id: 'd1', event: '$pageview', properties: {} },
                    person: { id: 'p1', properties: { email: 'customer@example.com' }, name: 'Customer', url: '' },
                })
            )
        })

        it.each([
            [
                'sends a real test only to the signed-in user',
                false,
                null,
                { to: { email: MOCK_DEFAULT_USER.email }, cc: '', bcc: '' },
                true,
            ],
            [
                'sends a real test only to the address typed for tests',
                false,
                'qa@example.com',
                { to: { email: 'qa@example.com' }, cc: '', bcc: '' },
                true,
            ],
            [
                'leaves the recipients of a mocked test as configured',
                true,
                'qa@example.com',
                {
                    to: { email: '{{ person.properties.email }}' },
                    cc: 'account-manager@example.com',
                    bcc: 'audit@example.com',
                },
                true,
            ],
            [
                'keeps the selected person recipient when enhanced testing is off',
                false,
                null,
                { to: { email: 'customer@example.com' }, cc: '', bcc: '' },
                false,
            ],
        ])('%s', async (_, mocked, typedAddress, expectedRecipients, enabled) => {
            featureFlagLogic.actions.setFeatureFlags(enabled ? ['workflows-testing-v2'] : [], {
                'workflows-testing-v2': enabled,
            })
            if (typedAddress) {
                logic.actions.setEmailAddressOverride(typedAddress)
            }
            logic.actions.setTestInvocationValue('mock_async_functions', mocked)

            await expectLogic(logic, () => logic.actions.submitTestInvocation()).toDispatchActions([
                'submitTestInvocationSuccess',
            ])

            expect(postedBody!.configuration.actions.map((action: Record<string, any>) => action.id)).toEqual([
                'welcome_email',
                'follow_up_email',
            ])
            for (const action of postedBody!.configuration.actions) {
                expect(action.config.inputs.email.value).toMatchObject({ ...expectedRecipients, subject: 'Welcome' })
            }
            expect(postedBody!.globals.person.properties.email).toEqual('customer@example.com')
            expect(postedBody!.testing_v2 ?? false).toEqual(enabled)
        })

        it.each([
            ['nothing is typed', (): void => {}, MOCK_DEFAULT_USER.email],
            [
                'an address is typed',
                (): void => logic.actions.setEmailAddressOverride('qa@example.com'),
                'qa@example.com',
            ],
            [
                'the typed address is cleared',
                (): void => {
                    logic.actions.setEmailAddressOverride('qa@example.com')
                    logic.actions.setEmailAddressOverride('')
                },
                MOCK_DEFAULT_USER.email,
            ],
            [
                'another user typed an address in this browser',
                (): void => {
                    logic.actions.setEmailAddressOverride('qa@example.com')
                    userLogic.actions.loadUserSuccess({
                        ...MOCK_DEFAULT_USER,
                        uuid: 'another-user',
                        email: 'another-user@example.com',
                    })
                },
                'another-user@example.com',
            ],
        ])('sends test emails to the right address when %s', (_, act, expectedAddress) => {
            act()

            expect(logic.values.testEmailAddress).toEqual(expectedAddress)
        })

        it.each([
            ['a mocked test with a half-typed address', true, 'qa@', null],
            ['a real send with a half-typed address', false, 'qa@', 'Must enter a valid email address'],
            ['a real send to your own address', false, '', null],
        ])('lets %s run only when the address it sends to is valid', (_, mocked, typedAddress, reason) => {
            logic.actions.setTestInvocationValue('mock_async_functions', mocked)
            logic.actions.setEmailAddressOverride(typedAddress)

            expect(logic.values.runTestDisabledReason).toEqual(reason)
        })
    })
})
