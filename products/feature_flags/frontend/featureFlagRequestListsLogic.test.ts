import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'

describe('featureFlagRequestListsLogic', () => {
    let logic: ReturnType<typeof featureFlagRequestListsLogic.build>
    let patchedPayload: Partial<TeamType> | undefined

    beforeEach(() => {
        patchedPayload = undefined
        useMocks({
            patch: {
                '/api/environments/:id': async ({ request }) => {
                    const payload = (await request.json()) as Partial<TeamType>
                    patchedPayload = payload
                    const config = payload.feature_flag_policy_config
                    return [
                        200,
                        {
                            ...MOCK_DEFAULT_TEAM,
                            feature_flag_policy_config: {
                                require_tags: false,
                                blocked_hosts: ['saved.example.com'],
                                blocked_ips: [],
                                ...config,
                                ...(config?.blocked_hosts && {
                                    blocked_hosts: config.blocked_hosts.map((host: string) => host.toLowerCase()),
                                }),
                            },
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = featureFlagRequestListsLogic()
        logic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            feature_flag_policy_config: { require_tags: false, blocked_hosts: ['saved.example.com'], blocked_ips: [] },
        })
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        [
            'a domain',
            () => logic.actions.setBlockedHosts(['saved.example.com', 'NEW.example.com']),
            { blocked_hosts: ['saved.example.com', 'NEW.example.com'] },
            { blockedHosts: ['saved.example.com', 'new.example.com'], blockedIps: [] },
        ],
        [
            'an IP address',
            () => logic.actions.setBlockedIps(['203.0.113.7']),
            { blocked_ips: ['203.0.113.7'] },
            { blockedHosts: ['saved.example.com'], blockedIps: ['203.0.113.7'] },
        ],
        [
            'an allowed domain',
            () => logic.actions.setAllowedHosts(['app.example.org']),
            { allowed_hosts: ['app.example.org'] },
            { blockedHosts: ['saved.example.com'], allowedHosts: ['app.example.org'], allowedIps: [] },
        ],
        [
            'an allowed IP address',
            () => logic.actions.confirmFirstAllowedIps(['198.51.100.0/24']),
            { allowed_ips: ['198.51.100.0/24'] },
            { blockedHosts: ['saved.example.com'], allowedHosts: [], allowedIps: ['198.51.100.0/24'] },
        ],
    ])('saves only the edited list after adding %s and shows what the API stored', async (_, edit, sent, shown) => {
        await expectLogic(logic, edit).toDispatchActions(teamLogic, ['updateCurrentTeamSuccess']).toMatchValues(shown)

        expect(patchedPayload?.feature_flag_policy_config).toEqual(sent)
    })

    it('asks before it saves the first allowed IP address, and not after that', async () => {
        await expectLogic(logic, () => logic.actions.setAllowedIps(['198.51.100.1'])).toMatchValues({
            firstAllowedIps: ['198.51.100.1'],
            allowedIps: [],
        })
        await expectLogic(logic, () => logic.actions.cancelFirstAllowedIps())
            .toFinishAllListeners()
            .toMatchValues({ firstAllowedIps: null })
        expect(patchedPayload).toBeUndefined()

        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            feature_flag_policy_config: { require_tags: false, allowed_ips: ['198.51.100.1'] },
        })
        await expectLogic(logic, () => logic.actions.setAllowedIps(['198.51.100.1', '198.51.100.2']))
            .toDispatchActions(teamLogic, ['updateCurrentTeamSuccess'])
            .toMatchValues({ firstAllowedIps: null, allowedIps: ['198.51.100.1', '198.51.100.2'] })
    })

    it('shows the saved list when the API rejects an entry', async () => {
        useMocks({
            patch: {
                '/api/environments/:id': () => [400, { type: 'validation_error', detail: 'Not a valid domain.' }],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setBlockedHosts(['saved.example.com', '*.example.com'])
        })
            .toDispatchActions(teamLogic, ['updateCurrentTeamFailure'])
            .toFinishAllListeners()

        expect(logic.values.blockedHosts).toEqual(['saved.example.com'])
    })
})
