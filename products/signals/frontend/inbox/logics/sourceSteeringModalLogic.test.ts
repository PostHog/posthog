import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SOURCE_STEERING_MAX_LENGTH, SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { sourceSteeringModalLogic } from './sourceSteeringModalLogic'

const sourceConfig: SignalSourceConfig = {
    id: 'config-1',
    source_product: SignalSourceProduct.Conversations,
    source_type: SignalSourceType.Ticket,
    enabled: true,
    // A key steering does not own, to prove saves merge rather than clobber.
    config: { recording_filters: { events: [] }, steering: 'old rules' },
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    status: null,
}

describe('sourceSteeringModalLogic', () => {
    let logic: ReturnType<typeof sourceSteeringModalLogic.build>
    let patchBodies: Record<string, any>[]
    let onClose: jest.Mock

    beforeEach(() => {
        patchBodies = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [sourceConfig], count: 1, next: null, previous: null },
                ],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    patchBodies.push(body)
                    return [200, { ...sourceConfig, ...body }]
                },
            },
        })
        initKeaTests()
        onClose = jest.fn()
        logic = sourceSteeringModalLogic({ sourceConfig, onClose })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('saves the whole config with trimmed steering keys merged in, keeping keys it does not own', async () => {
        expect(logic.values.sourceSteering).toEqual({ steering: 'old rules', defaultNotActionable: false })

        logic.actions.setSourceSteeringValue('steering', '  skip chores  ')
        logic.actions.setSourceSteeringValue('defaultNotActionable', true)
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringSuccess'])

        expect(patchBodies).toEqual([
            {
                config: {
                    recording_filters: { events: [] },
                    steering: 'skip chores',
                    default_not_actionable: true,
                },
            },
        ])
        expect(onClose).toHaveBeenCalled()
    })

    it('rejects rules over the server cap without issuing a request', async () => {
        logic.actions.setSourceSteeringValue('steering', 'x'.repeat(SOURCE_STEERING_MAX_LENGTH + 1))
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringFailure'])

        expect(patchBodies).toEqual([])
        expect(onClose).not.toHaveBeenCalled()
    })
})
