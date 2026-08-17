import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signalSourcesLogic } from '../signalSourcesLogic'
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
    let reloadFails: boolean

    beforeEach(() => {
        patchBodies = []
        reloadFails = false
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () =>
                    reloadFails
                        ? [500, { detail: 'Internal server error' }]
                        : [200, { results: [sourceConfig], count: 1, next: null, previous: null }],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    patchBodies.push(body)
                    // The serializer recomputes the sync status on every response.
                    return [200, { ...sourceConfig, ...body, status: 'completed' }]
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

    it('merges onto the freshest cached config, not the open-time snapshot', async () => {
        // A reload landed while the modal was open and changed a key steering does not own.
        signalSourcesLogic.actions.loadSourceConfigsSuccess([
            { ...sourceConfig, config: { ...sourceConfig.config, recording_filters: { events: ['$pageview'] } } },
        ])

        logic.actions.setSourceSteeringValue('steering', 'new rules')
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringSuccess'])

        expect(patchBodies[0].config.recording_filters).toEqual({ events: ['$pageview'] })
    })

    it('caches the saved config from the response even when the list reload fails', async () => {
        signalSourcesLogic.actions.loadSourceConfigsSuccess([sourceConfig])
        reloadFails = true

        logic.actions.setSourceSteeringValue('steering', 'fresh rules')
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringSuccess'])
        await expectLogic(signalSourcesLogic).toDispatchActions(['loadSourceConfigsFailure'])

        expect(signalSourcesLogic.values.sourceConfigs?.[0]?.config).toEqual({
            recording_filters: { events: [] },
            steering: 'fresh rules',
            default_not_actionable: false,
        })
        expect(signalSourcesLogic.values.sourceConfigs?.[0]?.status).toEqual('completed')
    })

    it('shows the saved rules when the same source is reopened after a config reload', () => {
        logic.unmount()
        const reloaded = {
            ...sourceConfig,
            config: { ...sourceConfig.config, steering: 'saved rules', default_not_actionable: true },
            updated_at: '2026-08-02T00:00:00Z',
        }
        logic = sourceSteeringModalLogic({ sourceConfig: reloaded, onClose })
        logic.mount()

        expect(logic.values.sourceSteering).toEqual({ steering: 'saved rules', defaultNotActionable: true })
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
