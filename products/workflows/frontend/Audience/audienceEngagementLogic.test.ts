import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { engagementEventsLogic } from '../engagementEventsLogic'
import { audienceEngagementLogic } from './audienceEngagementLogic'
import { AUDIENCE_ENGAGEMENT_TILES } from './audienceEngagementTiles'

const CREATED_DASHBOARD_ID = 42

const TEAM_WITH_ENGAGEMENT_EVENTS: TeamType = {
    ...MOCK_DEFAULT_TEAM,
    workflows_config: { capture_workflows_engagement_events: true },
}

const EXPECTED_TILE_QUERIES = [
    {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            dateRange: { date_from: '-30d' },
            series: [
                { event: '$workflows_email_sent' },
                { event: '$workflows_email_delivered' },
                { event: '$workflows_email_opened' },
                { event: '$workflows_email_link_clicked' },
            ],
        },
    },
    {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'week',
            dateRange: { date_from: '-30d' },
            series: [
                { event: '$workflows_email_unsubscribed' },
                { event: '$workflows_email_bounced' },
                { event: '$workflows_email_blocked' },
            ],
            trendsFilter: { display: 'ActionsBar' },
        },
    },
    {
        kind: 'InsightVizNode',
        source: {
            kind: 'FunnelsQuery',
            dateRange: { date_from: '-30d' },
            series: [
                { event: '$workflows_email_sent' },
                { event: '$workflows_email_delivered' },
                { event: '$workflows_email_opened' },
                { event: '$workflows_email_link_clicked' },
            ],
            funnelsFilter: { funnelAggregateByHogQL: 'properties.$email_to' },
        },
    },
]

function capturedEvents(eventName: string): unknown[][] {
    return jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === eventName)
}

describe('audience engagement', () => {
    let logic: ReturnType<typeof audienceEngagementLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('creates a dashboard from the three tile queries and opens it', async () => {
        let releaseCreation: () => void = () => {}
        const creationReleased = new Promise<void>((resolve) => {
            releaseCreation = resolve
        })
        const postedTemplates: Record<string, any>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/dashboards/create_from_template_json/': async ({ request }) => {
                    postedTemplates.push(((await request.json()) as Record<string, any>).template)
                    await creationReleased
                    return [200, { id: CREATED_DASHBOARD_ID }]
                },
            },
        })
        logic = audienceEngagementLogic()
        logic.mount()

        logic.actions.createDashboard()
        await expectLogic(logic).toMatchValues({ createdDashboardLoading: true })
        releaseCreation()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ createdDashboardLoading: false })

        expect(postedTemplates).toHaveLength(1)
        expect(postedTemplates[0].tiles).toMatchObject(EXPECTED_TILE_QUERIES.map((query) => ({ query })))
        expect(postedTemplates[0].tiles.map((tile: { query: unknown }) => tile.query)).toEqual(
            AUDIENCE_ENGAGEMENT_TILES.map((tile) => tile.query)
        )
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(`/dashboard/${CREATED_DASHBOARD_ID}`)
        expect(capturedEvents('audience dashboard created')).toEqual([
            ['audience dashboard created', { dashboard_id: CREATED_DASHBOARD_ID }],
        ])
    })

    it('with engagement events off, shows team-wide workflow metrics totals', async () => {
        const hogQLQueries: string[] = []
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    hogQLQueries.push(((await request.json()) as { query: { query: string } }).query.query)
                    return [
                        200,
                        {
                            results: [
                                [1200, 'email_sent'],
                                [1150, 'email_delivered'],
                                [480, 'email_opened'],
                                [96, 'email_link_clicked'],
                                [12, 'email_bounced'],
                                [2, 'email_blocked'],
                            ],
                        },
                    ]
                },
            },
        })
        logic = audienceEngagementLogic()

        await expectLogic(logic, () => {
            logic.mount()
        })
            .toFinishAllListeners()
            .toMatchValues({
                engagementEventsCaptured: false,
                metricsTotals: {
                    sent: 1200,
                    delivered: 1150,
                    opened: 480,
                    clicked: 96,
                    bounced: 12,
                    markedAsSpam: 2,
                },
            })
        expect(hogQLQueries).toHaveLength(1)
        expect(hogQLQueries[0]).toContain("app_source = 'hog_flow'")
        expect(hogQLQueries[0]).not.toContain('app_source_id')
    })

    it.each([
        {
            entryPoint: 'the Audience prompt',
            turnOn: () => engagementEventsLogic.actions.turnOnEngagementEvents('engagement'),
            expectedEvent: ['audience engagement events enabled', { surface: 'engagement' }],
        },
        {
            entryPoint: 'the settings switch',
            turnOn: () => engagementEventsLogic.actions.setEngagementEventsCapture(true),
            expectedEvent: ['workflows engagement events toggled', { enabled: true, surface: 'settings' }],
        },
    ])(
        'turning engagement events on from $entryPoint saves the setting and shows the tiles',
        async ({ turnOn, expectedEvent }) => {
            const teamUpdates: Partial<TeamType>[] = []
            useMocks({
                patch: {
                    '/api/projects/:team_id/': async ({ request }) => {
                        teamUpdates.push((await request.json()) as Partial<TeamType>)
                        return [200, TEAM_WITH_ENGAGEMENT_EVENTS]
                    },
                },
            })
            logic = audienceEngagementLogic()
            logic.mount()

            turnOn()
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(engagementEventsLogic).toFinishAllListeners()

            expect(teamUpdates).toEqual([
                expect.objectContaining({ workflows_config: { capture_workflows_engagement_events: true } }),
            ])
            expect(logic.values.engagementEventsCaptured).toBe(true)
            expect(capturedEvents(expectedEvent[0] as string)).toEqual([expectedEvent])
        }
    )
})
