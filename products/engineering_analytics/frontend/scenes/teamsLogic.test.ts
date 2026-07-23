import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsTeamCiHealth } from '../generated/api'
import { teamsLogic } from './teamsLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsTeamCiHealth: jest.fn(),
}))
jest.mock('./engineeringAnalyticsLogic', () => {
    const { actions, kea, path, reducers } = jest.requireActual('kea')
    return {
        engineeringAnalyticsLogic: kea([
            path(['test', 'engineeringAnalyticsLogic']),
            actions({ setSourceId: (sourceId: string | null) => ({ sourceId }) }),
            reducers({
                sourceId: [
                    null as string | null,
                    { setSourceId: (_: string | null, { sourceId }: { sourceId: string | null }) => sourceId },
                ],
            }),
        ]),
    }
})

const mockTeamCiHealth = engineeringAnalyticsTeamCiHealth as jest.MockedFunction<
    typeof engineeringAnalyticsTeamCiHealth
>

describe('teamsLogic', () => {
    let logic: ReturnType<typeof teamsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockTeamCiHealth.mockResolvedValue({
            items: [
                {
                    owner_team: 'team-zero',
                    has_test_activity: false,
                    flaky_test_count: 0,
                    flaky_test_count_prior: 0,
                    regression_test_count: 0,
                    regression_test_count_prior: 0,
                    failed_run_count: 0,
                    failed_run_count_prior: 0,
                    same_commit_recovery_run_count: 0,
                    same_commit_recovery_run_count_prior: 0,
                    quarantined_failed_run_count: 0,
                    quarantined_failed_run_count_prior: 0,
                    last_seen_at: null,
                },
            ],
            truncated: false,
            limit: 100,
            surface: 'all',
            has_ownership_catalog: true,
            ownership_catalog_captured_at: '2026-07-23T12:00:00Z',
        })
        logic = teamsLogic.build()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('keeps catalog teams with zero signals and reloads by surface', async () => {
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                testSurface: 'all',
                teams: {
                    rows: [expect.objectContaining({ ownerTeam: 'team-zero', hasTestActivity: false })],
                    truncated: false,
                    limit: 100,
                    hasOwnershipCatalog: true,
                },
            })
        expect(mockTeamCiHealth).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ surface: 'all' })
        )

        await expectLogic(logic, () => logic.actions.setTestSurface('frontend'))
            .toFinishAllListeners()
            .toMatchValues({ testSurface: 'frontend' })
        expect(mockTeamCiHealth).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ surface: 'frontend' })
        )
    })
})
