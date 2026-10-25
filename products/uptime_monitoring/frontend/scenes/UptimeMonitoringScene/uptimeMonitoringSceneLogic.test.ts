import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import type { UptimeMonitorApi } from '../../generated/api.schemas'
import { uptimeMonitoringSceneLogic } from './uptimeMonitoringSceneLogic'

const EXISTING: UptimeMonitorApi = {
    id: '01900000-0000-7000-8000-000000000001',
    team_id: 1,
    name: 'Marketing site',
    url: 'https://example.com',
    method: 'GET',
    interval_seconds: 300,
    timeout_seconds: 10,
    enabled: true,
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-20T10:00:00Z',
}

function setUptimeFlag(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.UPTIME_MONITORING] : [], {
        [FEATURE_FLAGS.UPTIME_MONITORING]: enabled,
    })
}

describe('uptimeMonitoringSceneLogic', () => {
    let listSpy: jest.SpyInstance
    let createSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        listSpy = jest.spyOn(generatedApi, 'uptimeMonitorsList').mockResolvedValue({ count: 1, results: [EXISTING] })
        createSpy = jest.spyOn(generatedApi, 'uptimeMonitorsCreate')
    })

    afterEach(() => {
        listSpy.mockRestore()
        createSpy.mockRestore()
    })

    it.each([
        ['on before mount', true, false, 1],
        ['off', false, false, 0],
        ['turned on after mount', false, true, 1],
    ])('loads monitors when the flag is %s', async (_, flagOnAtMount, flagOnAfterMount, expectedCalls) => {
        featureFlagLogic.mount()
        setUptimeFlag(flagOnAtMount)
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        if (flagOnAfterMount) {
            setUptimeFlag(true)
            await expectLogic(logic).toFinishAllListeners()
        }
        expect(listSpy).toHaveBeenCalledTimes(expectedCalls)
    })

    it('submitting the form creates the monitor, prepends it and closes the modal', async () => {
        featureFlagLogic.mount()
        setUptimeFlag(true)
        const created = { ...EXISTING, id: '01900000-0000-7000-8000-000000000002', name: 'API' }
        createSpy.mockResolvedValue(created)
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openCreateModal()
        logic.actions.setNewMonitorValues({ name: '  API  ', url: 'https://api.example.com' })
        await expectLogic(logic, () => logic.actions.submitNewMonitor()).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ name: 'API' }))
        expect(logic.values.monitors?.map((m) => m.id)).toEqual([created.id, EXISTING.id])
        expect(logic.values.isCreateModalOpen).toBe(false)
    })

    it('fetches the list again after a create that follows a failed load', async () => {
        featureFlagLogic.mount()
        setUptimeFlag(true)
        const created = { ...EXISTING, id: '01900000-0000-7000-8000-000000000002', name: 'API' }
        listSpy
            .mockRejectedValueOnce(new ApiError('Server error', 500))
            .mockResolvedValueOnce({ count: 2, results: [created, EXISTING] })
        createSpy.mockResolvedValue(created)
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.monitors).toBeNull()

        logic.actions.setNewMonitorValues({ name: 'API', url: 'https://api.example.com' })
        await expectLogic(logic, () => logic.actions.submitNewMonitor()).toFinishAllListeners()

        expect(logic.values.monitors?.map((m) => m.id)).toEqual([created.id, EXISTING.id])
    })

    it('shows a server validation error on its field, keeps the modal open and lets a fixed value retry', async () => {
        createSpy.mockRejectedValueOnce(
            new ApiError('Bad request', 400, undefined, { attr: 'url', detail: 'Enter a valid URL.' })
        )
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        logic.actions.openCreateModal()
        logic.actions.setNewMonitorValues({ name: 'Intranet', url: 'https://intranet' })
        await expectLogic(logic, () => logic.actions.submitNewMonitor()).toFinishAllListeners()
        expect(logic.values.newMonitorManualErrors).toEqual({ url: 'Enter a valid URL.' })
        expect(logic.values.isCreateModalOpen).toBe(true)

        createSpy.mockResolvedValueOnce({ ...EXISTING, url: 'https://intranet.example.com' })
        logic.actions.setNewMonitorValue('url', 'https://intranet.example.com')
        await expectLogic(logic, () => logic.actions.submitNewMonitor()).toFinishAllListeners()
        expect(createSpy).toHaveBeenCalledTimes(2)
    })

    it('refuses a URL without an http scheme', async () => {
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        logic.actions.setNewMonitorValues({ name: 'Site', url: 'example.com' })
        await expectLogic(logic, () => logic.actions.submitNewMonitor()).toFinishAllListeners()
        expect(createSpy).not.toHaveBeenCalled()
        expect(logic.values.newMonitorValidationErrors.url).toBeTruthy()
    })
})
