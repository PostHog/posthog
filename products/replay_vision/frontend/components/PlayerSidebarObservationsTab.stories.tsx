import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
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
    MEDIUM,
    MEDIUM_INACTIVE,
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

// The mock recording lasts 11 seconds, so key moments sit inside it to land on the seekbar.
const monitorWithReasoning = ((): ReplayObservationApi => {
    const monitor = checkoutMonitor(5_000)
    const output = monitor.scanner_result!.model_output as Record<string, unknown>
    return {
        ...monitor,
        scanner_result: {
            ...monitor.scanner_result!,
            model_output: {
                ...output,
                reasoning:
                    'The user applied a discount code twice, then the payment form rejected their card. They retried with a second card before the order went through.',
            },
        },
    } as ReplayObservationApi
})()

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
        // The player marks the recording viewed once it loads.
        patch: {
            '/api/projects/:team_id/session_recordings/:id/': recordingMetaJson,
            '/api/environments/:team_id/session_recordings/:id/': recordingMetaJson,
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
    title: 'Scenes-App/Replay Vision/Observations tab in the player',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-02',
        pageUrl: combineUrl(urls.replay(), {
            sessionRecordingId: SESSION_ID,
            sidebarTab: SessionRecordingSidebarTab.OBSERVATIONS,
            inspectorSideBar: true,
            pause: true,
            t: 1,
        }).url,
        waitForSelector: '[data-attr=vision-observations-tab]',
        testOptions: { waitForLoadersToDisappear: false },
    },
    // The player shows its controls for a moment after loading, so a snapshot taken then would flip between runs.
    play: async () => {
        await waitFor(
            () => {
                if (!document.querySelector('.PlayerSeekbar')?.closest('.invisible')) {
                    throw new Error('The player controls are still showing')
                }
            },
            { timeout: 10000 }
        )
    },
}
export default meta

type Story = StoryObj<{}>

// The timeline, an opened observation showing its reasoning, and two scans sharing one seekbar mark.
export const TimelineWithScans: Story = {
    decorators: [
        playerMocks([
            monitorWithReasoning,
            summary({ chapters: MEDIUM, inactive: MEDIUM_INACTIVE }),
            frustrationScorer(5_000),
            intentClassifier(8_000),
        ]),
    ],
}

// Without a summary the timeline section offers only the summarize button.
export const ScansWithoutASummary: Story = {
    decorators: [playerMocks([checkoutMonitor(5_000), frustrationScorer(8_000)])],
}
