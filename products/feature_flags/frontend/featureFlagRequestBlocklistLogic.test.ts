import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { featureFlagRequestBlocklistLogic } from './featureFlagRequestBlocklistLogic'

describe('featureFlagRequestBlocklistLogic', () => {
    let logic: ReturnType<typeof featureFlagRequestBlocklistLogic.build>
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
        logic = featureFlagRequestBlocklistLogic()
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
    ])('saves only the edited list after adding %s and shows what the API stored', async (_, edit, sent, shown) => {
        await expectLogic(logic, edit).toDispatchActions(teamLogic, ['updateCurrentTeamSuccess']).toMatchValues(shown)

        expect(patchedPayload?.feature_flag_policy_config).toEqual(sent)
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
