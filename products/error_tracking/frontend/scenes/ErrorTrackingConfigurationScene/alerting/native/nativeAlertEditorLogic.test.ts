import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    errorTrackingAlertsCreate,
    errorTrackingAlertsList,
    errorTrackingAlertsPreviewRetrieve,
    errorTrackingAlertsUpdate,
} from '../../../../generated/api'
import { ErrorTrackingAlertApi } from '../../../../generated/api.schemas'
import { draftFromAlert, nativeAlertEditorLogic, payloadFromDraft } from './nativeAlertEditorLogic'

jest.mock('../../../../generated/api', () => ({
    errorTrackingAlertsList: jest.fn(),
    errorTrackingAlertsCreate: jest.fn(),
    errorTrackingAlertsUpdate: jest.fn(),
    errorTrackingAlertsDestroy: jest.fn(),
    errorTrackingAlertsPartialUpdate: jest.fn(),
    errorTrackingAlertsPreviewRetrieve: jest.fn(),
}))

const mockPreview = jest.mocked(errorTrackingAlertsPreviewRetrieve)
const mockCreate = jest.mocked(errorTrackingAlertsCreate)
const mockUpdate = jest.mocked(errorTrackingAlertsUpdate)
const mockList = jest.mocked(errorTrackingAlertsList)

const existingAlert = {
    id: 'alert-1',
    name: 'Production errors',
    enabled: false,
    triggers: ['issue_reopened', 'issue_created'],
    filters: {
        events: [{ id: '$error_tracking_issue_created', type: 'events' }],
        properties: [{ key: 'environment', value: 'production', type: 'event', operator: 'exact' }],
        bytecode: ['_H', 1],
    },
    throttle_seconds: 3600,
    destinations: [
        {
            id: 'dest-1',
            channel_type: 'slack',
            integration_id: 7,
            config: { channel: 'C0123', channel_name: '#alerts' },
            last_delivered_at: null,
            last_failure_at: null,
            last_error: '',
            consecutive_failures: 0,
        },
    ],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
} as unknown as ErrorTrackingAlertApi

describe('nativeAlertEditorLogic', () => {
    let logic: ReturnType<typeof nativeAlertEditorLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockPreview.mockResolvedValue({ issue_id: null, messages: [] })
        mockList.mockResolvedValue({ count: 0, results: [] } as never)
        logic = nativeAlertEditorLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('round-trips an alert through the draft and splits the composite slack channel', () => {
        const draft = draftFromAlert(existingAlert)
        expect(draft.destinations).toEqual([{ integrationId: 7, channel: 'C0123|#alerts' }])
        expect(payloadFromDraft(draft)).toEqual({
            name: 'Production errors',
            enabled: false,
            triggers: ['issue_reopened', 'issue_created'],
            // Event filters the editor does not show survive the round trip; bytecode is server-owned.
            filters: { events: existingAlert.filters.events, properties: existingAlert.filters.properties },
            throttle_seconds: 3600,
            destinations: [
                { channel_type: 'slack', integration_id: 7, config: { channel: 'C0123', channel_name: '#alerts' } },
            ],
        })
    })

    it('previews the first selected trigger and blocks saving until a channel is picked', async () => {
        await expectLogic(logic, () => logic.actions.openEditor())
            .toDispatchActions(['loadPreview', 'loadPreviewSuccess'])
            .toMatchValues({ isOpen: true, saveDisabledReason: 'Give the alert a name' })
        expect(mockPreview).toHaveBeenLastCalledWith(expect.any(String), { trigger: 'issue_created' })

        logic.actions.setDraft({ name: 'Spikes' })
        logic.actions.setTriggerEnabled('issue_created', false)
        await expectLogic(logic, () => logic.actions.setTriggerEnabled('issue_spiking', true)).toFinishAllListeners()
        expect(mockPreview).toHaveBeenLastCalledWith(expect.any(String), { trigger: 'issue_spiking' })
        expect(logic.values.saveDisabledReason).toEqual('Pick a Slack workspace and channel')

        logic.actions.updateDestination(0, { integrationId: 7 })
        // A workspace without a channel would be dropped silently; saving stays blocked until it is complete.
        expect(logic.values.saveDisabledReason).toEqual(
            'Pick a channel for every Slack destination, or remove the empty one'
        )
        logic.actions.updateDestination(0, { channel: 'C0456|#spikes' })
        expect(logic.values.saveDisabledReason).toBeNull()

        mockCreate.mockResolvedValue(existingAlert)
        await expectLogic(logic, () => logic.actions.saveAlert()).toDispatchActions([
            'saveAlertSuccess',
            'closeEditor',
            'loadAlerts',
        ])
        expect(mockCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                name: 'Spikes',
                triggers: ['issue_spiking'],
                destinations: [
                    { channel_type: 'slack', integration_id: 7, config: { channel: 'C0456', channel_name: '#spikes' } },
                ],
            })
        )
        expect(logic.values.isOpen).toBe(false)
    })

    it('updates an existing alert with a full replacement payload', async () => {
        mockUpdate.mockResolvedValue(existingAlert)
        await expectLogic(logic, () => {
            logic.actions.openEditor(existingAlert)
            logic.actions.setDraft({ enabled: true })
            logic.actions.saveAlert()
        }).toDispatchActions(['saveAlertSuccess'])
        expect(mockUpdate).toHaveBeenCalledWith(
            expect.any(String),
            'alert-1',
            expect.objectContaining({ enabled: true, throttle_seconds: 3600 })
        )
    })
})
