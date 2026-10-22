import { expectLogic } from 'kea-test-utils'

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
        [true, 1],
        [false, 0],
    ])('loads monitors on mount only when the flag is %s', async (flagOn, expectedCalls) => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flagOn ? [FEATURE_FLAGS.UPTIME_MONITORING] : [], {
            [FEATURE_FLAGS.UPTIME_MONITORING]: flagOn,
        })
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(listSpy).toHaveBeenCalledTimes(expectedCalls)
    })

    it('submitting the form creates the monitor, prepends it and closes the modal', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.UPTIME_MONITORING], {
            [FEATURE_FLAGS.UPTIME_MONITORING]: true,
        })
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

    it('refuses a URL without an http scheme', async () => {
        const logic = uptimeMonitoringSceneLogic()
        logic.mount()
        logic.actions.setNewMonitorValues({ name: 'Site', url: 'example.com' })
        await expectLogic(logic, () => logic.actions.submitNewMonitor()).toFinishAllListeners()
        expect(createSpy).not.toHaveBeenCalled()
        expect(logic.values.newMonitorValidationErrors.url).toBeTruthy()
    })
})
