import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { GroupType, GroupTypeIndex } from '~/types'

import { buildGroupsFromEventRow, hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'

describe('buildGroupsFromEventRow', () => {
    const groupTypes = new Map<GroupTypeIndex, GroupType>([
        [2 as GroupTypeIndex, { group_type: 'organization', group_type_index: 2 as GroupTypeIndex } as GroupType],
    ])

    it('builds the groups map keyed by type from the event group columns', () => {
        const ids = [null, null, 'org-1', null, null]
        const props = [null, null, { billing_plan: 'scale' }, null, null]
        expect(buildGroupsFromEventRow(ids, props, groupTypes, 'http://localhost/project/1')).toEqual({
            organization: {
                id: 'org-1',
                type: 'organization',
                index: 2,
                url: 'http://localhost/project/1/groups/2/org-1',
                properties: { billing_plan: 'scale' },
            },
        })
    })

    it('skips empty ids and group indexes with no type mapping', () => {
        const ids = ['', null, 'org-1', 'acct-1', null] // index 3 has no type in the map
        const props = [{}, {}, { billing_plan: 'scale' }, { x: 1 }, {}]
        const result = buildGroupsFromEventRow(ids, props, groupTypes, 'http://localhost/project/1')
        expect(Object.keys(result ?? {})).toEqual(['organization'])
    })
})

describe('hogFlowEditorTestLogic', () => {
    let logic: ReturnType<typeof hogFlowEditorTestLogic.build>

    beforeEach(() => {
        initKeaTests()
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

    describe('testResult.groups', () => {
        beforeEach(() => {
            logic = hogFlowEditorTestLogic({ id: 'test-workflow' })
            logic.mount()
        })

        it('carries server-resolved groups through to the test result', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTestResult({
                    status: 'success',
                    nextActionId: 'next-step',
                    groups: { organization: { id: 'org-1', properties: { billing_plan: 'scale' } } },
                })
            }).toMatchValues({
                testResult: expect.objectContaining({
                    groups: { organization: { id: 'org-1', properties: { billing_plan: 'scale' } } },
                }),
            })
        })
    })
})
