import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionApi } from '../generated/api.schemas'
import { visionActionsLogic } from './visionActionsLogic'

const action = (id: string, enabled = true): VisionActionApi => ({
    id,
    name: `action-${id}`,
    scanner: 's1',
    enabled,
    trigger_config: { rrule: 'FREQ=DAILY' },
    delivery_config: [],
    next_run_at: null,
    last_run_at: null,
    hog_flow_id: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-01-01T00:00:00Z',
})

describe('visionActionsLogic', () => {
    let logic: ReturnType<typeof visionActionsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/': { results: [action('a'), action('b')], count: 2 },
            },
            patch: {
                '/api/projects/:team/vision/actions/:id/': () => [200, {}],
            },
            delete: {
                '/api/projects/:team/vision/actions/:id/': () => [204, null],
            },
        })
        initKeaTests()
        logic = visionActionsLogic({ scannerId: 's1' })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it("loads the scanner's actions on mount", async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadActions', 'loadActionsSuccess'])
            .toMatchValues({
                visionActions: expect.arrayContaining([
                    expect.objectContaining({ id: 'a' }),
                    expect.objectContaining({ id: 'b' }),
                ]),
            })
    })

    it('toggleActionEnabled optimistically flips the row and marks it in-flight', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadActionsSuccess([action('a', true)])
            logic.actions.toggleActionEnabled('a')
        }).toMatchValues({
            visionActions: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
            togglingIds: ['a'],
        })
    })

    it('revertActionEnabled flips the row back and clears the in-flight id', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadActionsSuccess([action('a', true)])
            logic.actions.toggleActionEnabled('a')
            logic.actions.revertActionEnabled('a')
        }).toMatchValues({
            visionActions: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: true })]),
            togglingIds: [],
        })
    })

    it('deleteActionSuccess removes the row', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadActionsSuccess([action('a'), action('b')])
            logic.actions.deleteActionSuccess('a')
        }).toMatchValues({
            visionActions: [expect.objectContaining({ id: 'b' })],
        })
    })
})
