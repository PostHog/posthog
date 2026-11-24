import type { Meta } from '@storybook/react'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'

import {
    alice,
    backfillEstimate,
    backfills,
    bob,
    estimate,
    monitorOverviewScanner,
    monitorOverviewStats,
    noSelfDrivingStats,
    observation,
    observationDetail,
    observations,
    observationsTrend,
    onDemandRecordings,
    paginated,
    quota,
    rootCauseFormScanner,
    runningExperiments,
    scannerStats,
    scanners,
    sessionPropertiesRow,
    spendSeries,
    summarizerScanner,
    summarizerStats,
} from './replayScannersStoryFixtures'
import scoutTemplates from './scoutTemplates.json'

export const replayScannersStoryConfig: Pick<Meta, 'parameters' | 'decorators'> = {
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-12',
        pageUrl: urls.replayVision(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tags/': { results: ['checkout', 'core flows'], next: null, count: 2 },
                '/api/projects/:team_id/experiments/': runningExperiments,
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/scanners/stats/': scannerStats,
                '/api/projects/:team_id/vision/scanners/creators/': { creators: [alice, bob] },
                // Two picks, then each filler kind. Only the first carries a key moment, so the rest show no time on the tile.
                '/api/projects/:team_id/vision/scanners/highlight_feed/': {
                    results: [
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d1',
                                prompt_question: 'Did the user hesitate at checkout?',
                                scanner_id: scanners.results[0].id,
                                scanner_snapshot: {
                                    name: 'Confused checkout',
                                    scanner_type: 'monitor',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: true,
                                    scanner_config: { prompt: 'Did the user hesitate at checkout?' },
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'monitor',
                                        verdict: 'yes',
                                        confidence: 0.92,
                                        reasoning: 'Retried the payment form twice before completing.',
                                        reasoning_segments: [
                                            { kind: 'chip', timestamp_ms: 62000 },
                                            { kind: 'text', value: ' Retried the payment form twice ' },
                                            { kind: 'chip', timestamp_ms: 154000 },
                                        ],
                                        key_moment_ms: 154000,
                                    },
                                    signals_count: 2,
                                },
                                viewed: false,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'failure', similar_count: 0 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d2',
                                prompt_question: 'How strong is the buying intent in this session?',
                                scanner_id: scanners.results[3].id,
                                scanner_snapshot: {
                                    name: 'Intent score',
                                    scanner_type: 'scorer',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: false,
                                    scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'scorer',
                                        score: 9.5,
                                        confidence: 0.88,
                                        reasoning: 'Compared plans, opened billing, invited a teammate.',
                                        reasoning_segments: [
                                            { kind: 'text', value: 'Compared plans at ' },
                                            { kind: 'chip', timestamp_ms: 30000 },
                                            { kind: 'text', value: ', opened billing, invited a teammate.' },
                                        ],
                                    },
                                    signals_count: 0,
                                },
                                viewed: false,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'revenue', similar_count: 0 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d3',
                                prompt_question: 'What happened in this session?',
                                recording_subject_email: 'bob@example.com',
                                viewed: true,
                            }),
                            reason: { kind: 'unviewed_recent' },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d4',
                                prompt_question: 'What happened in this session?',
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'summarizer',
                                        confidence: 0.8,
                                        title: 'Quick bug report',
                                        summary: 'Hit an error dialog and filed feedback from the toast.',
                                    },
                                    signals_count: 0,
                                },
                                viewed: true,
                            }),
                            reason: { kind: 'recent' },
                        },
                    ],
                },
                '/api/projects/:team_id/vision/quota/': quota,
                '/api/projects/:team_id/vision/quota/spend_series/': spendSeries,
                '/api/projects/:team_id/vision/scanners/:id/': ({ params }) =>
                    params.id === rootCauseFormScanner.id
                        ? rootCauseFormScanner
                        : params.id === monitorOverviewScanner.id
                          ? monitorOverviewScanner
                          : summarizerScanner,
                // Rendered by the backend's templates; only the root cause body is full, since only its form is shown.
                '/api/projects/:team_id/vision/scanners/:scannerId/scouts/templates/': ({ params }) =>
                    (params.scannerId === summarizerScanner.id
                        ? scoutTemplates.summarizer
                        : scoutTemplates.monitor
                    ).map((template) => ({
                        ...template,
                        body: template.body.replaceAll('SCANNER_ID', String(params.scannerId)),
                    })),
                '/api/projects/:team_id/vision/scanners/:id/self_driving_stats/': noSelfDrivingStats,
                '/api/projects/:team_id/vision/scanners/:id/observations/': observations,
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': ({ params }) =>
                    params.id === rootCauseFormScanner.id || params.id === monitorOverviewScanner.id
                        ? monitorOverviewStats
                        : summarizerStats,
                '/api/projects/:team_id/vision/observations/:id/': observationDetail,
                // Real bytes, so the poster in the table and on the detail page renders as a reader sees it.
                '/api/projects/:team_id/vision/observations/:id/thumbnail/': () => sessionFrameResponse(),
                '/api/projects/:team_id/vision/scanners/:scannerId/observations/:id/thumbnail/': () =>
                    sessionFrameResponse(),
                '/api/environments/:team_id/session_recordings/': { results: onDemandRecordings, has_next: false },
                '/api/environments/:team_id/session_recordings/matching_events': { results: [] },
                '/api/projects/:team_id/signals/scout/configs/': [],
                '/api/projects/:team_id/signals/scout/runs/recent-per-scout/': [],
                '/api/projects/:team_id/signals/scout/runs/findings/summary/': [],
                '/api/projects/:team_id/signals/scout/metadata/current/': {},
                '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [],
                '/api/projects/:team_id/vision/alerts/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/vision/scanners/:scannerId/backfills/': {
                    count: backfills.length,
                    next: null,
                    previous: null,
                    results: backfills,
                },
                // The three namespaces the pinned-properties picker offers.
                '/api/environments/:team_id/sessions/property_definitions/': paginated([
                    '$entry_referring_domain',
                    '$channel_type',
                    '$entry_utm_source',
                    '$entry_current_url',
                ]),
                // The observation page embeds the player, so it needs a recording to play.
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) =>
                    new URL(request.url).searchParams.get('source') === 'blob_v2'
                        ? new Response(snapshotsAsJSONLines())
                        : {
                              sources: [
                                  {
                                      source: 'blob_v2',
                                      start_timestamp: '2023-08-11T12:03:36.097000Z',
                                      end_timestamp: '2023-08-11T12:04:52.268000Z',
                                      blob_key: '0',
                                  },
                              ],
                          },
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                '/api/projects/:team_id/property_definitions/': ({ request }) => {
                    const type = new URL(request.url).searchParams.get('type')
                    return type === 'person'
                        ? paginated(['email', 'plan', 'company_size'])
                        : paginated(['$geoip_country_code', '$browser', '$device_type', '$os'])
                },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { kind?: string; query?: string } } | null
                    if (body?.query?.kind === 'EventsQuery') {
                        return recordingEventsJson
                    }
                    // The observation page's pinned strip is the only query aliasing its columns this way.
                    return body?.query?.query?.includes('as pinned_0')
                        ? { results: [sessionPropertiesRow] }
                        : observationsTrend
                },
                '/api/projects/:team_id/vision/observations/:id/label/': async ({ request }) => {
                    const body = (await request.json()) as { is_correct: boolean; feedback?: string }
                    return { is_correct: body.is_correct, feedback: body.feedback ?? '' }
                },
                '/api/projects/:team_id/vision/scanners/estimate/': estimate,
                '/api/projects/:team_id/vision/scanners/:scannerId/backfills/estimate/': backfillEstimate,
            },
        }),
    ],
}
