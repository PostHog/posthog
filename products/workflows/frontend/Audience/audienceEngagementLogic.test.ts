import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { engagementEventsLogic } from '../engagementEventsLogic'
import { audienceEngagementLogic } from './audienceEngagementLogic'
import { AUDIENCE_ENGAGEMENT_TILES } from './audienceEngagementTiles'
import { emailMetricsTotalsLogic } from './emailMetricsTotalsLogic'

const CREATED_DASHBOARD_ID = 42

const EXPECTED_TILE_QUERIES = [
    {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            dateRange: { date_from: '-30d' },
            series: [
                { event: '$workflows_email_sent', math: 'total' },
                { event: '$workflows_email_delivered', math: 'total' },
                { event: '$workflows_email_opened', math: 'total' },
                { event: '$workflows_email_link_clicked', math: 'total' },
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
                {
                    event: '$workflows_email_unsubscribed',
                    math: 'hogql',
                    math_hogql: 'count(DISTINCT properties.$email)',
                },
                { event: '$workflows_email_bounced', math: 'total' },
                { event: '$workflows_email_blocked', math: 'total' },
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
            funnelsFilter: {
                funnelAggregateByHogQL: 'properties.$email_to',
                funnelWindowInterval: 30,
                funnelWindowIntervalUnit: 'day',
            },
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
        jest.useRealTimers()
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it('creates a dashboard from the three tile queries and opens it', async () => {
        let releaseCreation: () => void = () => {}
        const creationReleased = new Promise<void>((resolve) => {
            releaseCreation = resolve
        })
        const postedBodies: Record<string, any>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/dashboards/create_from_template_json/': async ({ request }) => {
                    postedBodies.push((await request.json()) as Record<string, any>)
                    await creationReleased
                    return [200, { id: CREATED_DASHBOARD_ID, name: 'Email engagement', tiles: [] }]
                },
            },
        })
        logic = audienceEngagementLogic()
        logic.mount()

        logic.actions.createDashboard()
        await expectLogic(logic).toMatchValues({ createdDashboardLoading: true })
        releaseCreation()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ createdDashboardLoading: false })

        expect(postedBodies).toHaveLength(1)
        expect(postedBodies[0]._create_in_folder).toBe('Unfiled/Dashboards')
        const postedTiles = postedBodies[0].template.tiles
        expect(postedTiles).toMatchObject(EXPECTED_TILE_QUERIES.map((query) => ({ query })))
        expect(postedTiles.map((tile: { query: unknown }) => tile.query)).toEqual(
            AUDIENCE_ENGAGEMENT_TILES.map((tile) => tile.query)
        )
        expect(dashboardsModel.values.rawDashboards[CREATED_DASHBOARD_ID]).toMatchObject({ name: 'Email engagement' })
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(`/dashboard/${CREATED_DASHBOARD_ID}`)
        expect(capturedEvents('audience dashboard created')).toEqual([
            ['audience dashboard created', { dashboard_id: CREATED_DASHBOARD_ID }],
        ])
    })

    it('with engagement events off, shows team-wide workflow metrics totals for the last 30 days', async () => {
        jest.useFakeTimers({ now: new Date('2026-10-01T09:00:00Z'), advanceTimers: true })
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
        logic.mount()
        const totalsLogic = emailMetricsTotalsLogic()

        await expectLogic(totalsLogic, () => {
            totalsLogic.mount()
        })
            .toFinishAllListeners()
            .toMatchValues({
                metricsTotals: {
                    sent: 1200,
                    delivered: 1150,
                    opened: 480,
                    clicked: 96,
                    bounced: 12,
                    markedAsSpam: 2,
                },
            })
        totalsLogic.unmount()
        expect(logic.values.engagementEventsCaptured).toBe(false)
        expect(hogQLQueries).toHaveLength(1)
        expect(hogQLQueries[0]).toContain("app_source = 'hog_flow'")
        expect(hogQLQueries[0]).not.toContain('app_source_id')
        expect(hogQLQueries[0]).toContain("toDateTime('2026-09-01T00:00:00.000Z', 'UTC')")
        expect(hogQLQueries[0]).toContain("toDateTime('2026-10-01T09:00:00.000Z', 'UTC')")
    })

    it('with engagement events off, shows why the totals failed and loads them on retry', async () => {
        silenceKeaLoadersErrors()
        let queryFails = true
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () =>
                    queryFails ? [500, { detail: 'Query timed out' }] : [200, { results: [[1200, 'email_sent']] }],
            },
        })
        const totalsLogic = emailMetricsTotalsLogic()

        await expectLogic(totalsLogic, () => {
            totalsLogic.mount()
        })
            .toFinishAllListeners()
            .toMatchValues({ metricsTotals: null, metricsTotalsError: 'Query timed out' })

        queryFails = false
        await expectLogic(totalsLogic, () => {
            totalsLogic.actions.loadMetricsTotals()
        })
            .toFinishAllListeners()
            .toMatchValues({ metricsTotals: expect.objectContaining({ sent: 1200 }), metricsTotalsError: null })
        totalsLogic.unmount()
    })

    it('tracks which tile was opened as an insight', () => {
        logic = audienceEngagementLogic()
        logic.mount()

        logic.actions.insightOpened('funnel')

        expect(capturedEvents('audience insight opened')).toEqual([['audience insight opened', { tile: 'funnel' }]])
    })

    const CAPTURE_CHANGES = [
        {
            change: 'turning engagement events on from the Audience prompt',
            capturedBefore: false,
            save: () => engagementEventsLogic.actions.turnOnEngagementEvents('engagement'),
            expectedEvent: ['audience engagement events enabled', { surface: 'engagement' }],
        },
        {
            change: 'turning engagement events on from the settings switch',
            capturedBefore: false,
            save: () => engagementEventsLogic.actions.setEngagementEventsCapture(true),
            expectedEvent: ['workflows engagement events toggled', { enabled: true, surface: 'settings' }],
        },
        {
            change: 'turning engagement events off from the settings switch',
            capturedBefore: true,
            save: () => engagementEventsLogic.actions.setEngagementEventsCapture(false),
            expectedEvent: ['workflows engagement events toggled', { enabled: false, surface: 'settings' }],
        },
    ]

    it.each(
        CAPTURE_CHANGES.flatMap((change) => [
            { ...change, outcome: 'saves only that setting and tracks it', status: 200 },
            { ...change, outcome: 'keeps the setting and tracks nothing when the save is rejected', status: 403 },
        ])
    )('$change $outcome', async ({ capturedBefore, save, expectedEvent, status }) => {
        silenceKeaLoadersErrors()
        const capturedAfterSave = !capturedBefore
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: capturedBefore,
                email_tracking_consent_mode: 'off',
            },
        })
        const teamUpdates: Partial<TeamType>[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/': async ({ request }) => {
                    teamUpdates.push((await request.json()) as Partial<TeamType>)
                    return status === 200
                        ? [
                              200,
                              {
                                  ...MOCK_DEFAULT_TEAM,
                                  workflows_config: {
                                      capture_workflows_engagement_events: capturedAfterSave,
                                      email_tracking_consent_mode: 'opt_in',
                                  },
                              },
                          ]
                        : [403, { detail: "You don't have sufficient permissions in the project." }]
                },
            },
        })
        logic = audienceEngagementLogic()
        logic.mount()

        save()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(engagementEventsLogic).toFinishAllListeners()

        expect(teamUpdates).toEqual([{ workflows_config: { capture_workflows_engagement_events: capturedAfterSave } }])
        expect(logic.values.engagementEventsCaptured).toBe(status === 200 ? capturedAfterSave : capturedBefore)
        expect(capturedEvents(expectedEvent[0] as string)).toEqual(status === 200 ? [expectedEvent] : [])
    })
})
