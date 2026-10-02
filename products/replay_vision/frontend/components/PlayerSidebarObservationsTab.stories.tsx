import { Meta, StoryObj } from '@storybook/react'
import { combineUrl } from 'kea-router'

import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'
import { SessionRecordingSidebarTab } from '~/types'

import {
    LONG,
    LONG_INACTIVE,
    MEDIUM,
    MEDIUM_INACTIVE,
    MIN,
    checkoutMonitor,
    frustrationScorer,
    intentClassifier,
    summary,
} from '../__mocks__/recordingTimelineObservations'
import type { ReplayObservationApi } from '../generated/api.schemas'

const SESSION_ID = recordings[0].id

const quota = {
    credit_limit: 10000,
    credits_used: 2400,
    remaining: 7600,
    exhausted: false,
    projected_monthly_credits: 5200,
    scanners_monthly_credits: 5200,
    backfills_committed_credits: 0,
    free_monthly_credits: 2500,
    credits_settled: 2400,
    credits_reserved: 0,
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
}

const playerMocks = (observations: ReplayObservationApi[]): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings': { has_next: false, results: recordings, version: 1 },
            '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                    return new Response(snapshotsAsJSONLines())
                }
                return [
                    200,
                    {
                        sources: [
                            {
                                source: 'blob_v2',
                                start_timestamp: '2023-08-11T12:03:36.097000Z',
                                end_timestamp: '2023-08-11T12:04:52.268000Z',
                                blob_key: '0',
                            },
                        ],
                    },
                ]
            },
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/session_recording_playlists': { count: 0, results: [] },
            '/api/projects/:team_id/vision/observations/': {
                count: observations.length,
                next: null,
                previous: null,
                results: observations.map((o) => ({ ...o, session_id: SESSION_ID })),
            },
            '/api/projects/:team_id/vision/observations/:id/thumbnail/': () => sessionFrameResponse(),
            '/api/projects/:team_id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
            '/api/projects/:team_id/vision/quota/': quota,
        },
        post: {
            '/api/environments/:team_id/query/:kind': async ({ request }) => {
                const body = (await request.json()) as Record<string, any>
                if (body.query.kind === 'EventsQuery' && body.query.properties?.length === 1) {
                    return Response.json(recordingEventsJson)
                }
                return Response.json({ results: [] })
            },
        },
    })

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Observations tab',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-02',
        pageUrl: combineUrl(urls.replay(), {
            sessionRecordingId: SESSION_ID,
            sidebarTab: SessionRecordingSidebarTab.OBSERVATIONS,
            inspectorSideBar: true,
            pause: true,
            t: 7,
        }).url,
        waitForSelector: '[data-attr=vision-observations-tab]',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<{}>

export const ScansWithoutASummary: Story = {
    decorators: [playerMocks([checkoutMonitor(5_000), frustrationScorer(8_000), intentClassifier(2_000)])],
}

export const SummaryWithScans: Story = {
    decorators: [
        playerMocks([
            summary({ chapters: MEDIUM, inactive: MEDIUM_INACTIVE }),
            checkoutMonitor(221_000),
            frustrationScorer(240_000),
            intentClassifier(60_000),
        ]),
    ],
}

export const LongRecordingWithIdle: Story = {
    decorators: [playerMocks([summary({ chapters: LONG, inactive: LONG_INACTIVE }), checkoutMonitor(50 * MIN)])],
}

export const SummaryInProgress: Story = {
    decorators: [playerMocks([summary({ status: 'running' }), checkoutMonitor(5_000)])],
}
