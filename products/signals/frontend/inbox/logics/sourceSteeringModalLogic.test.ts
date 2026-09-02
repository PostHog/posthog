import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signalSourcesLogic } from '../signalSourcesLogic'
import { SOURCE_STEERING_MAX_LENGTH, SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { sourceHasLegacyPosture, sourceSteeringIsSet, sourceSteeringModalLogic } from './sourceSteeringModalLogic'

const sourceConfig: SignalSourceConfig = {
    id: 'config-1',
    source_product: SignalSourceProduct.Conversations,
    source_type: SignalSourceType.Ticket,
    enabled: true,
    // A key steering does not own, to prove saves merge rather than clobber.
    config: { recording_filters: { events: [] }, steering: 'old rules', default_not_actionable: true },
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    status: null,
}

describe('sourceSteeringModalLogic', () => {
    let logic: ReturnType<typeof sourceSteeringModalLogic.build>
    let patchBodies: Record<string, any>[]
    let patchedIds: string[]
    let onClose: jest.Mock
    let reloadFails: boolean
    let failingConfigId: string | null

    beforeEach(() => {
        patchBodies = []
        patchedIds = []
        reloadFails = false
        failingConfigId = null
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () =>
                    reloadFails
                        ? [500, { detail: 'Internal server error' }]
                        : [200, { results: [sourceConfig], count: 1, next: null, previous: null }],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request, params }) => {
                    if (String(params.id) === failingConfigId) {
                        return [500, { detail: 'Internal server error' }]
                    }
                    const body = (await request.json()) as Record<string, any>
                    patchBodies.push(body)
                    patchedIds.push(String(params.id))
                    // The serializer recomputes the sync status on every response.
                    return [200, { ...sourceConfig, ...body, status: 'completed' }]
                },
            },
        })
        initKeaTests()
        onClose = jest.fn()
        logic = sourceSteeringModalLogic({ sourceConfigs: [sourceConfig], onClose })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('saves the whole config with trimmed steering merged in, keeping keys it does not own and dropping the retired posture flag', async () => {
        expect(logic.values.sourceSteering).toEqual({ steering: 'old rules' })

        logic.actions.setSourceSteeringValue('steering', '  skip chores  ')
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringSuccess'])

        expect(patchBodies).toEqual([
            {
                config: {
                    recording_filters: { events: [] },
                    steering: 'skip chores',
                },
            },
        ])
        expect(onClose).toHaveBeenCalled()
    })

    it('saves one card of guidance to every row behind it', async () => {
        // Error tracking is one card over three config rows. Writing only the first would leave
        // reopened and spiking issues unfiltered, so the rules would look ignored half the time.
        logic.unmount()
        const rows: SignalSourceConfig[] = [
            SignalSourceType.IssueCreated,
            SignalSourceType.IssueReopened,
            SignalSourceType.IssueSpiking,
        ].map((sourceType) => ({
            ...sourceConfig,
            id: sourceType,
            source_product: SignalSourceProduct.ErrorTracking,
            source_type: sourceType,
            config: {},
        }))
        logic = sourceSteeringModalLogic({ sourceConfigs: rows, onClose })
        logic.mount()

        logic.actions.setSourceSteeringValue('steering', 'Ignore errors from localhost.')
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringSuccess'])

        expect(patchedIds).toEqual([
            SignalSourceType.IssueCreated,
            SignalSourceType.IssueReopened,
            SignalSourceType.IssueSpiking,
        ])
        expect(patchBodies).toEqual(rows.map(() => ({ config: { steering: 'Ignore errors from localhost.' } })))
    })

    it('keeps writing the remaining rows when one fails, and stays open to be retried', async () => {
        // Stopping at the failure would leave more triggers unfiltered than it has to, and closing
        // the modal would report a save the source did not get.
        logic.unmount()
        failingConfigId = String(SignalSourceType.IssueReopened)
        const rows: SignalSourceConfig[] = [
            SignalSourceType.IssueCreated,
            SignalSourceType.IssueReopened,
            SignalSourceType.IssueSpiking,
        ].map((sourceType) => ({
            ...sourceConfig,
            id: sourceType,
            source_product: SignalSourceProduct.ErrorTracking,
            source_type: sourceType,
            config: {},
        }))
        logic = sourceSteeringModalLogic({ sourceConfigs: rows, onClose })
        logic.mount()

        logic.actions.setSourceSteeringValue('steering', 'Ignore errors from localhost.')
        await expectLogic(logic, () => {
            logic.actions.submitSourceSteering()
        }).toDispatchActions(['submitSourceSteeringFailure'])

        expect(patchedIds).toEqual([SignalSourceType.IssueCreated, SignalSourceType.IssueSpiking])
        expect(onClose).not.toHaveBeenCalled()
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
        })
        expect(signalSourcesLogic.values.sourceConfigs?.[0]?.status).toEqual('completed')
    })

    it('shows the saved rules when the same source is reopened after a config reload', () => {
        logic.unmount()
        const reloaded = {
            ...sourceConfig,
            config: { ...sourceConfig.config, steering: 'saved rules' },
            updated_at: '2026-08-02T00:00:00Z',
        }
        logic = sourceSteeringModalLogic({ sourceConfigs: [reloaded], onClose })
        logic.mount()

        expect(logic.values.sourceSteering).toEqual({ steering: 'saved rules' })
    })

    it('still counts the retired posture flag as steering, so a filtering source is never shown as unset', () => {
        // The gate keeps honoring the flag, so a source carrying it alone must not read as
        // "no guidance" — that would leave it filtering with nothing to see or clear.
        const postureOnly = { ...sourceConfig, config: { default_not_actionable: true } }

        expect(sourceSteeringIsSet(postureOnly)).toBe(true)
        expect(sourceHasLegacyPosture(postureOnly)).toBe(true)
        expect(sourceHasLegacyPosture({ ...sourceConfig, config: { steering: 'text only' } })).toBe(false)
    })

    it('appends an example on its own line, and marks it unfittable rather than crossing the cap', () => {
        const [example] = logic.values.steeringExamples
        expect(example.fits).toBe(true)
        expect(example.result).toEqual(`old rules\n${example.line}`)

        // A near-full field: appending would cross the cap, which would leave the form unsavable.
        logic.actions.setSourceSteeringValue('steering', 'x'.repeat(SOURCE_STEERING_MAX_LENGTH - 5))

        expect(logic.values.steeringExamples.every((e) => e.fits)).toBe(false)
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
