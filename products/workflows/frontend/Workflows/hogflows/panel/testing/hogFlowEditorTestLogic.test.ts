import { MOCK_DEFAULT_ORGANIZATION, MOCK_GROUP_TYPES } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, GroupType, GroupTypeIndex, OrganizationType } from '~/types'

import {
    createGlobalsFromResponse,
    groupSelectColumns,
    hogFlowEditorTestLogic,
    parseGroupsFromResult,
} from './hogFlowEditorTestLogic'

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

    beforeEach(() => {
        initKeaTests()
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
