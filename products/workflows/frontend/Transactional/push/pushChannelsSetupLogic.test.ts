import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { pushChannelsSetupLogic } from './pushChannelsSetupLogic'

const APNS = {
    id: 1,
    kind: 'apns',
    display_name: 'com.example.app',
    icon_url: '',
    created_at: '',
    config: { bundle_id: 'com.example.app' },
} as IntegrationType
const FIREBASE = {
    id: 2,
    kind: 'firebase',
    display_name: 'example-project',
    icon_url: '',
    created_at: '',
    config: { project_id: 'example-project' },
} as IntegrationType

describe('pushChannelsSetupLogic', () => {
    let logic: ReturnType<typeof pushChannelsSetupLogic.build>

    let connected: IntegrationType[] = []

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': () => [200, { results: connected, next: null }],
                '/api/projects/:project_id/integrations': () => [200, { results: connected, next: null }],
            },
        })
        initKeaTests()
    })

    async function mountWith(integrations: IntegrationType[]): Promise<void> {
        connected = integrations
        logic = pushChannelsSetupLogic()
        logic.mount()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
    }

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        { name: 'no push app is connected', integrations: [], channels: [], counts: {}, warning: null },
        {
            name: 'the selected app was disconnected',
            integrations: [FIREBASE],
            channels: [1],
            counts: {},
            warning: 'app_disconnected',
        },
        {
            name: 'no selected app has a device',
            integrations: [APNS, FIREBASE],
            channels: [1, 2],
            counts: { 'com.example.app': 0, 'example-project': 0 },
            warning: 'no_devices',
        },
        {
            name: 'one selected app has a device',
            integrations: [APNS, FIREBASE],
            channels: [1, 2],
            counts: { 'com.example.app': 0, 'example-project': 4 },
            warning: null,
        },
        { name: 'no channel is picked yet', integrations: [APNS], channels: [], counts: {}, warning: null },
    ])('picks the warning when $name', async ({ integrations, channels, counts, warning }) => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query) => {
            const appId = Object.keys(counts).find((id) => String(query).includes(id))
            return { results: [[appId ? counts[appId as keyof typeof counts] : 0]] } as HogQLQueryResponse
        })
        await mountWith(integrations)

        await expectLogic(logic, () => logic.actions.setChannels(channels)).toFinishAllListeners()

        expect(logic.values.warning?.kind ?? null).toEqual(warning)
    })

    it('does not warn about devices while their count is still loading', async () => {
        let resolveCount: (response: HogQLQueryResponse) => void = () => {}
        jest.spyOn(api, 'queryHogQL').mockReturnValue(new Promise((resolve) => (resolveCount = resolve)))
        await mountWith([APNS])

        logic.actions.setChannels([1])
        expect(logic.values.warning).toBeNull()

        resolveCount({ results: [[0]] } as HogQLQueryResponse)
        await expectLogic(logic).toDispatchActions(['loadDeviceCountsSuccess'])
        expect(logic.values.warning).toEqual({ kind: 'no_devices', appNames: ['com.example.app'] })
    })
})
