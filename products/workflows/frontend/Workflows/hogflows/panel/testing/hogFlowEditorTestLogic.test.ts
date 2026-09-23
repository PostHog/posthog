import { MOCK_DEFAULT_ORGANIZATION, MOCK_GROUP_TYPES } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { performWideEventsQueryInTwoPhases } from 'scenes/hog-functions/sampleEventsQuery'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, GroupType, GroupTypeIndex, OrganizationType } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import { encodeSlackFilters } from '../../registry/triggers/slackTriggerFilters'
import { createExampleEventForTrigger } from '../../testEventFactory'
import {
    createGlobalsFromResponse,
    groupSelectColumns,
    hogFlowEditorTestLogic,
    parseGroupsFromResult,
} from './hogFlowEditorTestLogic'

jest.mock('scenes/hog-functions/sampleEventsQuery', () => ({
    ...jest.requireActual('scenes/hog-functions/sampleEventsQuery'),
    performWideEventsQueryInTwoPhases: jest.fn(),
}))

// Mounting hogFlowEditorTestLogic mounts workflowLogic, whose afterMount loads the hog
// flow; without a valid fixture the editor's resetFlowFromHogFlow crashes and logs.
const WORKFLOW_FIXTURE = {
    id: 'test-workflow',
    name: 'Test workflow',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} },
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
}

describe('hogFlowEditorTestLogic', () => {
    let logic: ReturnType<typeof hogFlowEditorTestLogic.build>

    const groupTypes = new Map<GroupTypeIndex, GroupType>([
        [0 as GroupTypeIndex, { group_type: 'organization', group_type_index: 0 } as GroupType],
        [1 as GroupTypeIndex, { group_type: 'project', group_type_index: 1 } as GroupType],
    ])

    describe('groupSelectColumns', () => {
        it('produces one tuple column per group type', () => {
            const columns = groupSelectColumns(groupTypes)
            expect(columns).toHaveLength(2)
            expect(columns[0]).toContain('organization')
            expect(columns[0]).toContain('.key')
            expect(columns[0]).toContain('.properties')
            expect(columns[1]).toContain('project')
        })

        it('returns nothing when there are no group types', () => {
            expect(groupSelectColumns(new Map())).toEqual([])
        })
    })

    describe('parseGroupsFromResult', () => {
        it('maps group tuples to resolved groups with key and properties', () => {
            const result = [
                { uuid: 'e1' },
                { id: 'p1' },
                ['2021-01-01', 0, 'org-1', JSON.stringify({ plan: 'enterprise' }), '2021-01-02'],
                ['2021-01-01', 1, 'proj-1', JSON.stringify({ tier: 'gold' }), '2021-01-02'],
            ]

            const groups = parseGroupsFromResult(result, groupTypes)

            expect(groups.organization).toMatchObject({
                type: 'organization',
                index: 0,
                id: 'org-1',
                properties: { plan: 'enterprise' },
            })
            expect(groups.organization.url).toContain('/groups/0/org-1')
            expect(groups.project).toMatchObject({ id: 'proj-1', properties: { tier: 'gold' } })
        })

        it('aligns columns by position when group type indices are non-contiguous', () => {
            // Only group type index 1 exists (index 0 absent) — column sits at result[2], not result[3]
            const sparseGroupTypes = new Map<GroupTypeIndex, GroupType>([
                [1 as GroupTypeIndex, { group_type: 'project', group_type_index: 1 } as GroupType],
            ])
            const result = [
                { uuid: 'e1' },
                { id: 'p1' },
                ['2021-01-01', 1, 'proj-1', JSON.stringify({ tier: 'gold' }), '2021-01-02'],
            ]

            const groups = parseGroupsFromResult(result, sparseGroupTypes)
            expect(groups.project).toMatchObject({ index: 1, id: 'proj-1', properties: { tier: 'gold' } })
        })

        it('skips group types with no matching group on the event', () => {
            const result = [{ uuid: 'e1' }, { id: 'p1' }, ['2021-01-01', 0, '', '{}', '2021-01-02']]
            expect(parseGroupsFromResult(result, groupTypes)).toEqual({})
        })

        it('falls back to empty properties on malformed JSON', () => {
            const result = [{ uuid: 'e1' }, { id: 'p1' }, ['2021-01-01', 0, 'org-1', 'not json', '2021-01-02']]
            expect(parseGroupsFromResult(result, groupTypes).organization.properties).toEqual({})
        })
    })

    describe('createGlobalsFromResponse groups', () => {
        const event = {
            uuid: 'e1',
            distinct_id: 'd1',
            timestamp: '2021-01-01',
            elements_chain: '',
            event: '$pageview',
            properties: {},
        }

        it('includes the groups passed in', () => {
            const groups = parseGroupsFromResult(
                [event, { id: 'p1', properties: {} }, ['2021-01-01', 0, 'org-1', '{}', '2021-01-02']],
                groupTypes
            )
            const globals = createGlobalsFromResponse(event, { id: 'p1', properties: {} }, 1, 'wf', groups)
            expect(globals.groups?.organization?.id).toEqual('org-1')
        })

        it('defaults groups to an empty object', () => {
            const globals = createGlobalsFromResponse(event, undefined, 1, 'wf')
            expect(globals.groups).toEqual({})
        })
    })

    describe('createExampleEventForTrigger', () => {
        it('builds a slack message example for Slack-connected triggers, seeded from the channel filter', () => {
            const properties = encodeSlackFilters({
                channels: ['C0ALERTS|#alerts', 'C0INCIDENTS|#incidents'],
                posterMode: 'anyone',
                posterIds: [],
                topLevelOnly: false,
                additional: [],
            })

            const globals = createExampleEventForTrigger(
                {
                    type: 'internal-event',
                    filters: {
                        source: 'internal-events',
                        events: [{ id: '$slack_message_received', type: 'events' }],
                        properties,
                    },
                },
                1,
                'wf'
            )

            expect(globals.event.event).toEqual('$slack_message_received')
            expect(globals.event.properties.channel).toEqual('C0ALERTS')
            // Slack-triggered runs are person-less, so the example must not invent one
            expect(globals.person).toBeUndefined()
            // The flat property bag the webhook emitter produces, which trigger filters read
            expect(globals.event.properties).toMatchObject({
                channel_type: 'channel',
                subtype: null,
                thread_ts: null,
                is_thread_reply: false,
                is_ext_shared_channel: false,
            })
            expect(Object.keys(globals.event.properties)).toEqual(
                expect.arrayContaining([
                    'integration_id',
                    'slack_team_id',
                    'user',
                    'bot_id',
                    'app_id',
                    'text',
                    'ts',
                    'slack_event',
                ])
            )
        })

        it('falls back to a default channel when the trigger has no channel filter', () => {
            const globals = createExampleEventForTrigger(
                {
                    type: 'internal-event',
                    filters: { source: 'internal-events', events: [{ id: '$slack_message_received', type: 'events' }] },
                },
                1,
                'wf'
            )

            expect(globals.event.event).toEqual('$slack_message_received')
            expect(typeof globals.event.properties.channel).toEqual('string')
        })

        // Each native poster mode compiles to a different property filter (slackTriggerFilters.ts).
        // A sample seeding only channel satisfies 'anyone' by accident and rejects every other mode.
        it.each([
            ['people', [] as string[], (props: Record<string, any>) => expect(props.bot_id).toBeNull()],
            ['apps', [] as string[], (props: Record<string, any>) => expect(props.bot_id).not.toBeNull()],
            [
                'specific_people',
                ['U0999999999'],
                (props: Record<string, any>) => expect(props.user).toEqual('U0999999999'),
            ],
            [
                'specific_apps',
                ['A0999999999'],
                (props: Record<string, any>) => expect(props.app_id).toEqual('A0999999999'),
            ],
        ])('seeds a sample that satisfies the %s poster filter', (posterMode, posterIds, assertion) => {
            const properties = encodeSlackFilters({
                channels: ['C0ALERTS'],
                posterMode: posterMode as any,
                posterIds,
                topLevelOnly: false,
                additional: [],
            })

            const globals = createExampleEventForTrigger(
                {
                    type: 'internal-event',
                    filters: {
                        source: 'internal-events',
                        events: [{ id: '$slack_message_received', type: 'events' }],
                        properties,
                    },
                },
                1,
                'wf'
            )

            assertion(globals.event.properties)
        })

        it('returns the standard example event for event triggers', () => {
            const globals = createExampleEventForTrigger({ type: 'event', filters: {} }, 1, 'wf')

            expect(globals.event.event).toEqual('$pageview')
            expect(globals.person).not.toBeUndefined()
        })
    })

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: { '/api/environments/:team_id/hog_flows/:id/': WORKFLOW_FIXTURE },
            // The editor autosaves, so a test that waits long enough reaches the save handler.
            // Echo the body back, or the saved edit is reverted by the response.
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => [
                    200,
                    { ...WORKFLOW_FIXTURE, ...((await request.json()) as Record<string, any>) },
                ],
            },
        })
        // clearMocks keeps implementations, so a test that installs one would otherwise hand it
        // to every test that runs after it.
        ;(performWideEventsQueryInTwoPhases as jest.Mock).mockReset()
    })

    describe('sample event follows the trigger filters', () => {
        it('reloads the sample event when the trigger filters change', async () => {
            // The panel fetched once on mount, so editing the trigger filters left the tester running
            // against an event that no longer matched the filters on screen.
            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()
            const flowLogic = workflowLogic({ id: 'test-workflow' })
            hogFlowEditorLogic({ id: 'test-workflow' }).actions.setMode('test')

            // Consume the load that mounting always does, so the assertion below can only pass on a
            // second one. Without this the test passes even when nothing reacts to the filters.
            await expectLogic(logic).toDispatchActions(['loadSampleGlobals'])

            const before = logic.values.matchingFilters

            await expectLogic(logic, () => {
                flowLogic.actions.setWorkflowValue(
                    'actions',
                    WORKFLOW_FIXTURE.actions.map((action) =>
                        action.id === 'trigger_node'
                            ? {
                                  ...action,
                                  config: {
                                      type: 'event',
                                      filters: { events: [{ id: '$pageview', type: 'events', properties: [] }] },
                                  },
                              }
                            : action
                    )
                )
            }).toDispatchActions(['loadSampleGlobals'])

            expect(logic.values.matchingFilters).not.toEqual(before)
        })

        it('reloads the sample event for a trigger that follows an event picked by name', async () => {
            // The by-name selector renders only for a trigger this panel cannot query, so the
            // picked name outlives that trigger. It must not stop the panel from following the
            // filters once the trigger is one the panel does query.
            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()
            const flowLogic = workflowLogic({ id: 'test-workflow' })
            hogFlowEditorLogic({ id: 'test-workflow' }).actions.setMode('test')

            const setTriggerConfig = (config: Record<string, any>): void => {
                flowLogic.actions.setWorkflowValue(
                    'actions',
                    WORKFLOW_FIXTURE.actions.map((action) =>
                        action.id === 'trigger_node' ? { ...action, config } : action
                    )
                )
            }

            // Consume the load that mounting always does, so the assertion below can only pass on
            // a later one.
            await expectLogic(logic).toDispatchActions(['loadSampleGlobals'])
            await expectLogic(flowLogic).toDispatchActions(['loadWorkflowSuccess'])

            setTriggerConfig({ type: 'webhook', filters: {} })
            logic.actions.loadSampleEventByName({ eventName: '$pageview' })
            expect(logic.values.lastSearchedEventName).toEqual('$pageview')

            await expectLogic(logic, () => {
                setTriggerConfig({
                    type: 'event',
                    filters: { events: [{ id: 'user logged in', type: 'events', properties: [] }] },
                })
            }).toDispatchActions(['loadSampleGlobals'])
        })

        it('follows the test-account toggle, in the reload and in the query', async () => {
            // The live trigger folds the team's test-account filters in, so a sample that ignores
            // the toggle can be an event the trigger would reject.
            const queryMock = performWideEventsQueryInTwoPhases as jest.Mock
            queryMock.mockReset()
            queryMock.mockImplementation(async () => ({ results: [] }))

            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()
            const flowLogic = workflowLogic({ id: 'test-workflow' })
            hogFlowEditorLogic({ id: 'test-workflow' }).actions.setMode('test')
            await expectLogic(logic).toDispatchActions(['loadSampleGlobalsSuccess'])

            expect(queryMock.mock.calls[0][0].filterTestAccounts).toBe(false)
            queryMock.mockClear()

            await expectLogic(logic, () => {
                flowLogic.actions.setWorkflowValue(
                    'actions',
                    WORKFLOW_FIXTURE.actions.map((action) =>
                        action.id === 'trigger_node'
                            ? { ...action, config: { type: 'event', filters: { filter_test_accounts: true } } }
                            : action
                    )
                )
            }).toDispatchActions(['loadSampleGlobals'])
            await expectLogic(logic).toDispatchActions(['loadSampleGlobalsSuccess'])

            expect(logic.values.shouldFilterTestAccounts).toBe(true)
            expect(queryMock.mock.calls[0][0].filterTestAccounts).toBe(true)
        })

        it('holds the reload until the test tab opens', async () => {
            // The build tab mounts this panel for its output mapping, so a filter edit there must
            // not spend a query on someone who never opens the tester.
            const queryMock = performWideEventsQueryInTwoPhases as jest.Mock
            queryMock.mockReset()
            queryMock.mockImplementation(async () => ({ results: [] }))

            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()
            const flowLogic = workflowLogic({ id: 'test-workflow' })
            hogFlowEditorLogic({ id: 'test-workflow' }).actions.setMode('build')
            await expectLogic(logic).toDispatchActions(['loadSampleGlobalsSuccess'])
            queryMock.mockClear()

            await expectLogic(logic, () => {
                flowLogic.actions.setWorkflowValue(
                    'actions',
                    WORKFLOW_FIXTURE.actions.map((action) =>
                        action.id === 'trigger_node'
                            ? { ...action, config: { type: 'event', filters: { filter_test_accounts: true } } }
                            : action
                    )
                )
            }).toDispatchActions(['markSampleGlobalsStale'])
            expect(queryMock).not.toHaveBeenCalled()

            await expectLogic(logic, () => {
                hogFlowEditorLogic({ id: 'test-workflow' }).actions.setMode('test')
            }).toDispatchActions(['loadSampleGlobals', 'loadSampleGlobalsSuccess'])

            expect(queryMock).toHaveBeenCalledTimes(1)
            expect(queryMock.mock.calls[0][0].filterTestAccounts).toBe(true)
        })

        it('keeps the newest sample event when an older query answers last', async () => {
            // Two loads overlap and the first query answers second. The stale answer must be
            // discarded, or the panel shows an event the current filters never asked for.
            const eventRow = (uuid: string): any[] => [
                { uuid, event: '$pageview', distinct_id: 'd1', properties: {}, timestamp: '2026-05-01T00:00:00Z' },
                { id: 'p1', properties: {} },
            ]
            let releaseStale: (() => void) | undefined
            const queryMock = performWideEventsQueryInTwoPhases as jest.Mock
            queryMock.mockReset()
            queryMock
                .mockImplementationOnce(
                    async () =>
                        await new Promise((resolve) => {
                            releaseStale = () => resolve({ results: [eventRow('stale-event')] })
                        })
                )
                .mockImplementation(async () => ({ results: [eventRow('fresh-event')] }))

            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSampleGlobals'])
            while (!releaseStale) {
                await new Promise((resolve) => setTimeout(resolve, 20))
            }

            logic.actions.loadSampleGlobals({})
            await expectLogic(logic).toDispatchActions(['loadSampleGlobalsSuccess'])
            expect(logic.values.sampleGlobals?.event?.uuid).toEqual('fresh-event')

            releaseStale!()
            await new Promise((resolve) => setTimeout(resolve, 50))

            expect(logic.values.sampleGlobals?.event?.uuid).toEqual('fresh-event')
        })

        it('keeps the newest sample event when an older query fails last', async () => {
            // The same overlap, but the older query fails for a real reason. Its failure belongs to
            // a load nobody is waiting for, so it must neither clear the event nor raise an error.
            const eventRow = (uuid: string): any[] => [
                { uuid, event: '$pageview', distinct_id: 'd1', properties: {}, timestamp: '2026-05-01T00:00:00Z' },
                { id: 'p1', properties: {} },
            ]
            let failStale: (() => void) | undefined
            const queryMock = performWideEventsQueryInTwoPhases as jest.Mock
            queryMock.mockReset()
            queryMock
                .mockImplementationOnce(
                    async () =>
                        await new Promise((_resolve, reject) => {
                            failStale = () => reject(new Error('query failed'))
                        })
                )
                .mockImplementation(async () => ({ results: [eventRow('fresh-event')] }))

            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSampleGlobals'])
            while (!failStale) {
                await new Promise((resolve) => setTimeout(resolve, 20))
            }

            logic.actions.loadSampleGlobals({})
            await expectLogic(logic).toDispatchActions(['loadSampleGlobalsSuccess'])
            expect(logic.values.sampleGlobals?.event?.uuid).toEqual('fresh-event')

            failStale!()
            await new Promise((resolve) => setTimeout(resolve, 50))

            expect(logic.values.sampleGlobals?.event?.uuid).toEqual('fresh-event')
            expect(logic.values.sampleGlobalsError).toBeNull()
        })

        it('still reports a failure that no later load supersedes', async () => {
            const queryMock = performWideEventsQueryInTwoPhases as jest.Mock
            queryMock.mockReset()
            queryMock.mockImplementation(async () => {
                throw new Error('query failed')
            })

            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSampleGlobals', 'setSampleGlobalsError'])
            expect(logic.values.sampleGlobalsError).toEqual('Failed to load matching events. Please try again.')
        })
    })

    describe('groupTypesForTest gating on group_analytics', () => {
        const orgWithFeatures = (features: AvailableFeature[]): OrganizationType => ({
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: features.map((key) => ({ key, name: key })),
        })

        it('exposes all group types when group_analytics is available', () => {
            initKeaTests(true, undefined as any, undefined as any, orgWithFeatures([AvailableFeature.GROUP_ANALYTICS]))
            useMocks({ get: { '/api/projects/:team/groups_types': MOCK_GROUP_TYPES } })
            useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS])
            groupsModel.mount()
            groupsModel.actions.loadAllGroupTypesSuccess(MOCK_GROUP_TYPES)
            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()

            expect(logic.values.groupsEnabled).toBe(true)
            expect(logic.values.groupTypesForTest.size).toBe(MOCK_GROUP_TYPES.length)
            expect(groupSelectColumns(logic.values.groupTypesForTest)).toHaveLength(MOCK_GROUP_TYPES.length)
        })

        it('resolves no group types without group_analytics, matching gated real execution', () => {
            initKeaTests(true, undefined as any, undefined as any, orgWithFeatures([]))
            useMocks({ get: { '/api/projects/:team/groups_types': MOCK_GROUP_TYPES } })
            useAvailableFeatures([])
            groupsModel.mount()
            // Group types load ungated, mirroring groupsModel.afterMount in real usage
            groupsModel.actions.loadAllGroupTypesSuccess(MOCK_GROUP_TYPES)
            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()

            expect(logic.values.groupsEnabled).toBe(false)
            // groupsModel still loaded the types ungated...
            expect(logic.values.groupTypes.size).toBe(MOCK_GROUP_TYPES.length)
            // ...but the test run must not use them, so no group columns are queried and groups stay empty
            expect(logic.values.groupTypesForTest.size).toBe(0)
            expect(groupSelectColumns(logic.values.groupTypesForTest)).toEqual([])
        })
    })

    describe('accumulatedVariables reducer', () => {
        beforeEach(() => {
            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()
        })

        it('starts with empty object', () => {
            expect(logic.values.accumulatedVariables).toEqual({})
        })

        it('merges variables from test result', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'next-step',
                    variables: { has_chat_runs: 'true', count: 5 },
                })
            }).toMatchValues({
                accumulatedVariables: { has_chat_runs: 'true', count: 5 },
            })
        })

        it('accumulates variables across multiple test results', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-2',
                    variables: { var1: 'value1' },
                })
            }).toMatchValues({
                accumulatedVariables: { var1: 'value1' },
            })

            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-3',
                    variables: { var2: 'value2' },
                })
            }).toMatchValues({
                accumulatedVariables: { var1: 'value1', var2: 'value2' },
            })
        })

        it('overwrites existing variables with new values', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-2',
                    variables: { counter: 1 },
                })
            }).toMatchValues({
                accumulatedVariables: { counter: 1 },
            })

            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-3',
                    variables: { counter: 2 },
                })
            }).toMatchValues({
                accumulatedVariables: { counter: 2 },
            })
        })

        it('does not modify state when test result has no variables', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-2',
                    variables: { existing: 'value' },
                })
            }).toMatchValues({
                accumulatedVariables: { existing: 'value' },
            })

            const stateBefore = logic.values.accumulatedVariables

            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-3',
                    // No variables in this result
                })
            })

            // State reference should be the same (no unnecessary re-render)
            expect(logic.values.accumulatedVariables).toBe(stateBefore)
        })

        it('resets on resetAccumulatedVariables action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-2',
                    variables: { var1: 'value1' },
                })
            }).toMatchValues({
                accumulatedVariables: { var1: 'value1' },
            })

            await expectLogic(logic, () => {
                logic.actions.resetAccumulatedVariables()
            }).toMatchValues({
                accumulatedVariables: {},
            })
        })

        it('resets on loadSampleGlobals action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-2',
                    variables: { var1: 'value1' },
                })
            }).toMatchValues({
                accumulatedVariables: { var1: 'value1' },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSampleGlobals({})
            }).toMatchValues({
                accumulatedVariables: {},
            })
        })

        it('resets on loadSampleEventByName action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'step-2',
                    variables: { var1: 'value1' },
                })
            }).toMatchValues({
                accumulatedVariables: { var1: 'value1' },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSampleEventByName({ eventName: '$pageview' })
            }).toMatchValues({
                accumulatedVariables: {},
            })
        })
    })
})
