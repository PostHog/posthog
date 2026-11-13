import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { membersLogic } from '~/models/membersLogic'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInvocationGlobals, PersonType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { hogFlowEditorNotificationTestLogic } from './hogFlowEditorNotificationTestLogic'

jest.mock('~/queries/query', () => {
    const actual = jest.requireActual('~/queries/query')
    return {
        ...actual,
        performQuery: jest.fn().mockResolvedValue({ results: [] }),
    }
})

const SANDBOX_STEP = {
    id: 'email',
    type: 'email_sandbox',
    name: 'Email',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { inputs: { email: { templating: 'liquid', value: { to: { email: 'ops@example.com' } } } } },
} as HogFlowAction

const ACCEPTED = { status: 'success', logs: [], nextActionId: null, execResult: { status: 'accepted' } }

function member(firstName: string, verified: boolean): Record<string, unknown> {
    const uuid = `u-${firstName.toLowerCase()}`
    return {
        id: `membership-${uuid}`,
        level: 1,
        joined_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        user: {
            uuid,
            first_name: firstName,
            email: `${firstName.toLowerCase()}@example.com`,
            is_email_verified: verified,
        },
    }
}

const MEMBERS = [member('Bo', true), member('Cy', false), member('Ana', true)]

describe('hogFlowEditorNotificationTestLogic', () => {
    let logic: ReturnType<typeof hogFlowEditorNotificationTestLogic.build>
    let workflowLogicInstance: ReturnType<typeof workflowLogic.build>

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()

        useMocks({
            get: {
                '/api/environments/:team_id/persons/': { results: [] },
                '/api/environments/:team_id/hog_flows/test-workflow-id/': {
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

    describe('sandbox step test', () => {
        let sentTo: string[]
        let personEmails: string[]

        beforeEach(() => {
            sentTo = []
            personEmails = []
            useMocks({
                get: { '/api/organizations/@current/members/': { results: MEMBERS, next: null } },
                post: {
                    '/api/environments/:team_id/hog_flows/:id/invocations': async ({ request }) => {
                        const { configuration, globals } = (await request.json()) as {
                            configuration: HogFlow
                            globals: { person: { properties: { email: string } } }
                        }
                        sentTo.push((configuration.actions[0].config as any).inputs.email.value.to.email)
                        personEmails.push(globals.person.properties.email)
                        return [200, ACCEPTED]
                    },
                },
            })
        })

        async function openSandboxTest(chosen: string): Promise<void> {
            await expectLogic(workflowLogicInstance).toDispatchActions(['loadWorkflowSuccess'])
            workflowLogicInstance.actions.setWorkflowValues({ actions: [SANDBOX_STEP] })
            logic.actions.setTestInvocationValue('globals', '{"person": {"properties": {"email": "lead@example.com"}}}')
            logic.actions.setTestInvocationValue('mock_async_functions', true)
            logic.actions.setEmailAddressOverride(chosen)
            logic.actions.setSelectedNodeId('email')
            membersLogic.actions.ensureAllMembersLoaded()
            await expectLogic(membersLogic).toFinishAllListeners()
        }

        it.each([
            ['an address outside the organization', 'lead@example.com', 'ana@example.com'],
            ['a member who has not verified their email', 'cy@example.com', 'ana@example.com'],
            ['a verified member', 'bo@example.com', 'bo@example.com'],
        ])('sends a sandbox step test chosen for %s only to a verified member', async (_, chosen, expected) => {
            await openSandboxTest(chosen)

            await expectLogic(logic, () => logic.actions.submitTestInvocation()).toDispatchActions([
                'submitTestInvocationSuccess',
            ])

            expect(sentTo).toEqual([expected])
            expect(personEmails).toEqual([expected])
        })

        it.each([
            ['the members load after the confirmation opened', 'confirmed', true],
            ['the member lookup failed', 'confirmed', false],
            ['the member lookup failed', 'mocked', false],
        ])('sends nothing from a sandbox step when %s (%s run)', async (_, run, membersLoad) => {
            if (!membersLoad) {
                useMocks({ get: { '/api/organizations/@current/members/': () => [500, { detail: 'Unavailable' }] } })
            }
            await openSandboxTest('lead@example.com')

            if (run === 'confirmed') {
                logic.actions.sendTestTo('lead@example.com')
            } else {
                logic.actions.submitTestInvocation()
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(sentTo).toEqual([])
        })

        it.each([
            [
                'no member has verified their email',
                { results: [member('Cy', false)], next: null },
                'No one in your organization has verified their email address yet. Verify yours to send a sandbox test.',
            ],
            [
                'the member lookup failed',
                () => [500, { detail: 'Unavailable' }],
                "Couldn't load your organization's members. Refresh the page to try again.",
            ],
        ])('explains why a sandbox step test cannot run when %s', async (_, membersResponse, reason) => {
            useMocks({ get: { '/api/organizations/@current/members/': membersResponse } })

            await openSandboxTest('lead@example.com')

            expect(logic.values.testRecipientDisabledReason).toEqual(reason)
        })

        it('stops showing a sandbox test result once the tested step moves to an own sender', async () => {
            await openSandboxTest('ana@example.com')
            await expectLogic(logic, () => logic.actions.submitTestInvocation()).toDispatchActions([
                'submitTestInvocationSuccess',
            ])
            expect(logic.values.testResult?.execResult).toEqual({ status: 'accepted' })

            workflowLogicInstance.actions.setWorkflowAction('email', {
                ...SANDBOX_STEP,
                type: 'function_email',
            } as HogFlowAction)

            expect(logic.values.testResult).toBeNull()
        })

        it('waits for the members before it judges who can receive a sandbox step test', async () => {
            await expectLogic(workflowLogicInstance).toDispatchActions(['loadWorkflowSuccess'])
            workflowLogicInstance.actions.setWorkflowValues({ actions: [SANDBOX_STEP] })
            logic.actions.setSelectedNodeId('email')

            expect(logic.values.testRecipientDisabledReason).toEqual('Loading verified members')
        })

        it('records a sandbox test send for the tested step after the selection moves on, and shows no result on the next step', async () => {
            const events: { event: string; properties: unknown }[] = []
            jest.mocked(posthog.capture).mockImplementation((event, properties) => {
                events.push({ event, properties })
                return undefined
            })
            let answer: () => void = () => {}
            const answered = new Promise<void>((resolve) => {
                answer = resolve
            })
            await openSandboxTest('ana@example.com')
            logic.actions.setTestInvocationValue('mock_async_functions', false)
            useMocks({
                post: {
                    '/api/environments/:team_id/hog_flows/:id/invocations': async () => {
                        await answered
                        return [200, ACCEPTED]
                    },
                },
            })

            logic.actions.submitTestInvocation()
            logic.actions.setSelectedNodeId(null)
            answer()
            await expectLogic(logic).toDispatchActions(['submitTestInvocationSuccess'])

            expect(events.filter(({ event }) => event.startsWith('workflows sandbox'))).toEqual([
                { event: 'workflows sandbox test sent', properties: { status: 'accepted', reason: null } },
            ])
            expect(logic.values.testResult).toBeNull()
        })
    })
})
