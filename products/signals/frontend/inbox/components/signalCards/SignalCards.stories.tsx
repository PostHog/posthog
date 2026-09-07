import type { Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'

import { FEATURE_FLAGS } from 'lib/constants'
import type { SignalNode } from 'scenes/debug/signals/types'

import { mswDecorator } from '~/mocks/browser'

import { SignalCard } from '../../SignalCard'

const BASE_DATE = '2026-06-10T09:30:00Z'

// Tiny generated screenshots so the preview frames and attachment thumbnails have something to show.
const RECORDING_PREVIEW_PNG =
    'iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAADVElEQVR42u3dsW7TUBQG4N+oVCgvEIrUAbFELB0RE0IsbH3WbCwVYkIdWVAX1AGJwMiAQ+IhbCxIUYOT1Pf6+9ZKbU/dX+de39in2Ww2Acr0wJ8ABBgQYECAYSROtnytvWyO9ntM5u6lgQ4MAgwUv4Quws3nT/2/yez5Ra3fHx0YEGBAgIG/mi2fhXaMBDowIMDATktoQAcGBBgQYKjJSbf+XXoND08fuZD4LHSp2l8/XUgsoQEBBgQYEGAQYECAAQEGBBgEGMgwP4m1+Pb1fn+5syfnrhDowCDAgAADAgwIMMTzwOX48X1RTS3Tx2dqrLjGvgGu9RTn6bNZBVXcfrlRY/U1WkKDPTAgwEDcxNqX648fjvODXrx8pUY16sCAAIMAAwIMxPPAqeOehBrVqAODAAMCDAgwIMAgwECGf4zkra6gAwMCDAgwCDAgwIAAgwADAgzE88BJfJIEvJUy+34XvhrVOBzNerUsvQN33cqFxB4YEGBAgAEBhoz0JlYp3MQijpFGwvR6NZZSowDH9Ho11n2abQ8McRMLEGDAHjgmu6txHFPUdGCwhAY8DxzPA4MODDpwTHZXoxp1YECAAQEGAQZiPjCgA4MAAwIMCDAgwCDAgAADAgzE88CgAwMCDHigPya7qzGGm5W2BzbcDEtoQIAB84FjPjDowCDAQBwjDYLp9WospUYBjun1aqz7NNsSGuyBAQEG7IFjsrsaRzJFzfPAYAkNCDAgwBA3sWKyuxrVqAMDAgyYDww6MCDAgACDAAMCDAgwIMAgwIAAAwIMCDDE44Twj/ay2de3mm79UlvIH2Qy3+jAgA6cxPT6A5tK1RGvxegC3GcOjRqHs3QsaCtx0MthCQ1xFxoQYECAQYCBOEYaFtPr7/cY6f3Vu/r+qV6/edvnX67PbeoxngObXn9QbdjhWvQ8JbaEBntgQIABe+CY7B7T63VgQAeG3PHEBR0YBBiwhI7J7mpEgCFHfyNXSnh1gSU02AMDAgwIMAgwIMCAAANxDkzlxvY2eR0YBBiwhCY+1YgODAIMWEIT94Hz3+++3vLy+jre760Dgw4cE9PVqMbyNOvVsvQaum7lQmIJDQgwIMCAAIMAAwIMCDAgwCDAgAADAgwCDAgwcHB/AE6//T5WJpdMAAAAAElFTkSuQmCC'
const ATTACHMENT_PNG =
    'iVBORw0KGgoAAAANSUhEUgAAAPAAAACgCAIAAAC9uXYyAAAC5klEQVR42u3cvWoUYRQG4HckinegEQyIRYKNpVgFsbHLtaazEbESSxvZLUIggtmUKWLcnWK9gVnIhsnsN988TxlIcpx9czzzd5r1eh2oxSOHAIEGgYaHt9f51YOTeb+/5uL00LFGhwaBxshRjtmvn9t+y9Gbt+X/HHRoEGgEGqrRdN76dtkOHRpK7dCgQ4NAg0DDJnvt6l9pNT1+8tQHQyW3vpP8vbn2wWDkAIFGoEGgQaBBoBFoEGjISG6sXP75/aC/df/FS4ceHRoEGoEGgQZP293L1eKyzMKePd9X6gClbh3o8q9CvHp9VFpJ52czpQ5WqpEDMzSYoYf04/u3Hn/au/fHSh1XqTo0Rg4QaBBomPbTdgOfcChVhwaBBoEGgUagIWO7yuGdP3RoEGgQaBBoBBoEGgQa4mk7qOWdwm3fbldqZaVu0qyWt6V16LZd6jSYoUGgEWgY2Qy9W2ZoYvtorPSM7aOjvWxnpWdsHzVD46QQzNCxfVSpto+CQIOn7dChwUlh7MlUqg4NAg0Cjd12oEODQINAI9Ag0CDQINAQT9uhQ4NAg8dHY6WnUmP7KBg5iN12sdsOHRoEGmL7qJWesX3U9tFY6RnbR8EMDWboWOmpVE/bgZEDgQaBBieFVnoqVYcGu+0wQ4NAg0CDQCPQINAg0CDQINAINAg0xNN29OTgZH7fb22SRdcX5zv851ycHto+OvFSm5r+Pns5UKMM9FabR6oudVFToHs5VkaOGvTyn/UIBycnhcRVDhBoiMt2sX00073KselY2T6ayaz07D6d+vrlc8mf3YePn+5+oGwfxQwNZujYPpqprPTUoUGgwa1vcufLCDo06NCxJ9NpnECTyp+DyyDPBho5MEODQINAg0Aj0CDQENehiZfJdWjQoeOWnhkaBBqMHOzspO38bNa5caHAd+ltH1XqJErdpFktb0urqW2Xui9maBBoBBoEGgQaBBqBBoEGgQaBBoFGoGHs/gP0Uf5WkRgQ5wAAAABJRU5ErkJggg=='

function pngResponse(base64: string): Response {
    return new HttpResponse(
        Uint8Array.from(atob(base64), (char) => char.charCodeAt(0)),
        {
            headers: { 'Content-Type': 'image/png' },
        }
    )
}

function makeSignal(
    overrides: Omit<Partial<SignalNode>, 'extra'> & {
        source_product: SignalNode['source_product']
        extra: Record<string, unknown>
    }
): SignalNode {
    return {
        signal_id: `sig-${overrides.source_product}`,
        content: 'The user retried the upload three times before leaving the page.',
        source_type: 'issue',
        source_id: 'src-1',
        weight: 0.8,
        timestamp: BASE_DATE,
        ...overrides,
        extra: overrides.extra as unknown as SignalNode['extra'],
    }
}

const sessionProblemExtra: Record<string, unknown> = {
    session_id: 'sess-1',
    segment_title: 'Upload retry loop',
    start_time: '01:12',
    end_time: '02:40',
    problem_type: 'failure',
    distinct_id: 'user-8f3a1c2d9e',
    session_start_time: '2026-06-11T09:00:00Z',
    session_duration: 412,
    session_active_seconds: 180,
    exported_asset_id: 101,
    event_history: [
        {
            event: '$pageview',
            timestamp: '01:12',
            current_url: 'https://app.example.com/files',
            event_type: 'pageview',
        },
        { event: '$autocapture', timestamp: '01:20', interaction_text: 'Upload', event_type: 'click' },
        {
            event: '$exception',
            timestamp: '01:31',
            interaction_text: 'Request failed with 413',
            event_type: 'exception',
        },
        { event: '$autocapture', timestamp: '02:38', interaction_text: 'Upload', event_type: 'click' },
    ],
}

const sessionProblem = makeSignal({
    source_product: 'session_replay',
    source_type: 'session_problem',
    source_id: 'sess-1',
    content: 'Three attempts to upload a 40 MB PDF failed with a 413, then the user abandoned the folder.',
    extra: sessionProblemExtra,
})

const sessionProblemWithoutScreenshot = makeSignal({
    ...sessionProblem,
    signal_id: 'sig-session-plain',
    extra: { ...sessionProblemExtra, exported_asset_id: null },
})

const scannerFinding = makeSignal({
    source_product: 'replay_vision',
    source_type: 'scanner_finding',
    source_id: 'obs-1',
    content: 'The share dialog opened with no close control and the user pressed Escape four times.',
    extra: {
        scanner_id: 'scanner-1',
        scanner_name: 'Dead-end modal',
        scanner_type: 'ux',
        observation_id: 'obs-1',
        session_id: 'sess-2',
        confidence: 0.82,
        problem_type: 'dead_end',
        start_time: 72,
        end_time: 90,
        url: 'https://app.example.com/files/shared',
        exported_asset_id: 102,
        distinct_id: 'user-2b7d4e6f1a',
        recording_start_time: '2026-06-11T08:40:00Z',
        recording_duration: 600,
        recording_active_seconds: 240,
    },
})

const conversationsTicket = makeSignal({
    source_product: 'conversations',
    source_type: 'ticket',
    source_id: 'ticket-4821',
    content: 'Customer reports the upload progress bar reaches 100% but the file never appears in the folder.',
    extra: {
        ticket_number: 4821,
        channel_source: 'email',
        channel_detail: null,
        status: 'open',
        priority: 'high',
        created_at: BASE_DATE,
        email_subject: 'Upload stuck at 100%',
        images: [
            { url: '/api/projects/997/exports/103/content/', author: 'Sam' },
            { url: '/api/projects/997/exports/104/content/', author: 'Sam' },
        ],
    },
})

// An error tracking payload with no fingerprint fails that card's guard, so it falls back to the
// generic card, which still links the issue from the source id.
const genericWithEntityLink = makeSignal({
    source_product: 'error_tracking',
    source_type: 'issue_created',
    source_id: 'issue-1',
    content: 'TypeError: cannot read properties of undefined (reading "size") in startUpload.',
    extra: {},
})

const genericWithExternalLink = makeSignal({
    source_product: 'jira',
    source_id: 'HB-12',
    content: 'Tracked as a bug by the platform team.',
    extra: { url: 'https://example.atlassian.net/browse/HB-12' },
})

const genericWithoutLink = makeSignal({
    source_product: 'jira',
    source_id: 'HB-13',
    content: 'Mentioned in the sprint retro notes.',
    extra: {},
})

const scoutFinding = makeSignal({
    source_product: 'signals_scout',
    source_type: 'cross_source_issue',
    source_id: 'finding-1',
    content: 'Upload failures rose after the 2.4.0 release.',
    extra: {
        scout_run_id: 'run-1a2b3c4d5e6f',
        task_run_id: 'taskrun-9f8e7d6c5b',
        task_id: 'task-1',
        finding_id: 'finding-1a2b3c4d',
        skill_name: 'upload-health',
        skill_version: 3,
        confidence: 0.85,
        severity: 'P1',
        hypothesis: 'The 2.4.0 release raised the client-side chunk size above the 413 limit on the upload endpoint.',
        evidence: [
            { source_product: 'error_tracking', entity_id: 'issue-1', summary: '413 errors up 6x since the release.' },
            { source_product: 'session_replay', entity_id: 'sess-1', summary: 'Users retry the upload and leave.' },
        ],
        tags: ['uploads', 'regression'],
        time_range: { date_from: '2026-06-09T00:00:00Z', date_to: '2026-06-10T00:00:00Z' },
    },
})

const errorTrackingIssue = makeSignal({
    source_product: 'error_tracking',
    source_type: 'issue_spiking',
    source_id: 'issue-2',
    content: 'RequestEntityTooLarge: upload chunk exceeds 10 MB.',
    extra: { fingerprint: 'fp-upload-413' },
})

// The real signal content carries the issue's full stack trace as a code fence (it is written for
// the report LLM, see `emit_issue_lifecycle_signal`), so a fixture with a long one pins the
// three-line cap the card applies to it.
const STACK_TRACE = [
    'RequestEntityTooLarge: upload chunk exceeds 10 MB',
    'handle_upload in app/api/uploads.py line 214',
    'validate_request in app/api/middleware.py line 61',
    'process_chunks in app/uploads/chunking.py line 88',
    'next_chunk in app/uploads/chunking.py line 47',
    'write_chunk in app/uploads/storage.py line 132',
    'put_object in app/clients/object_store.py line 55',
    'with_retries in app/clients/retry.py line 29',
    'inner in contextlib.py line 85',
    'request in httpclient/session.py line 402',
    'send in httpclient/adapters.py line 318',
    'raise_for_status in httpclient/models.py line 761',
    'handle_error in app/clients/object_store.py line 71',
    'to_upload_error in app/uploads/errors.py line 18',
    'log_failure in app/uploads/telemetry.py line 33',
    'capture in analytics/client.py line 96',
    'enqueue in analytics/queue.py line 54',
    'flush in analytics/queue.py line 78',
    'run in concurrent/futures/thread.py line 58',
    '_bootstrap_inner in threading.py line 1038',
    '_bootstrap in threading.py line 995',
].join('\n')

const errorTrackingIssueWithStackTrace = makeSignal({
    source_product: 'error_tracking',
    source_type: 'issue_created',
    source_id: 'issue-3',
    content: `New error tracking issue created - this particular exception was observed for the first time:\nRequestEntityTooLarge: upload chunk exceeds 10 MB\n\n\`\`\`\n${STACK_TRACE}\n\`\`\``,
    extra: { fingerprint: 'fp-upload-413-created' },
})

const healthCheck = makeSignal({
    source_product: 'health_checks',
    source_type: 'health_issue',
    source_id: 'hc-1',
    content: 'The web SDK is three minor versions behind.',
    extra: {
        kind: 'sdk_outdated',
        severity: 'warning',
        issue_id: 'hc-1',
        title: 'Outdated SDK',
        summary: 'The web SDK is three minor versions behind.',
        link: '/settings/project#sdk',
        url: '/settings/project#sdk',
        payload: { current_version: '1.240.0', latest_version: '1.243.1' },
    },
})

const githubIssue = makeSignal({
    source_product: 'github',
    source_type: 'issue',
    source_id: 'gh-512',
    content: 'Large uploads fail with 413 after upgrading to 2.4.0.',
    extra: {
        html_url: 'https://github.com/example/app/issues/512',
        number: 512,
        labels: ['bug', 'uploads'],
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
        locked: false,
        state: 'open',
    },
})

const linearIssue = makeSignal({
    source_product: 'linear',
    source_type: 'issue',
    source_id: 'lin-1',
    content: 'Raise the upload chunk limit on the API.',
    extra: {
        url: 'https://linear.app/example/issue/APP-88',
        identifier: 'APP-88',
        number: 88,
        priority: 2,
        priority_label: 'High',
        labels: ['backend'],
        state_name: 'In progress',
        state_type: 'started',
        team_name: 'Platform',
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
    },
})

const zendeskTicket = makeSignal({
    source_product: 'zendesk',
    source_type: 'ticket',
    source_id: 'zd-7',
    content: 'My 40 MB PDF will not upload.',
    extra: {
        url: 'https://example.zendesk.com/agent/tickets/7',
        type: 'problem',
        tags: ['uploads', 'enterprise'],
        created_at: BASE_DATE,
        priority: 'high',
        status: 'open',
    },
})

const pgAnalyzeIssue = makeSignal({
    source_product: 'pganalyze',
    source_type: 'issue',
    source_id: 'pg-1',
    content: 'Sequential scan on `uploads` for the folder listing query.',
    extra: {
        severity: 'high',
        references: [{ kind: 'table', name: 'uploads', url: null, queryText: null }],
        database_id: 'db-1',
        server_human_id: 'primary',
        server_name: 'app-primary',
        synced_at: BASE_DATE,
    },
})

const logsAlert = makeSignal({
    source_product: 'logs',
    source_type: 'alert_state_change',
    source_id: 'alert-1',
    content:
        'Logs alert "Upload 413s" is firing: log count went above the threshold of 50 over a 15m window (observed 312). Services: upload-api. Severities: error.',
    extra: {
        alert_id: 'alert-1',
        alert_name: 'Upload 413s',
        action: 'firing',
        threshold_count: 50,
        threshold_operator: 'above',
        window_minutes: 15,
        result_count: 312,
        consecutive_failures: 0,
        filters: { serviceNames: ['upload-api'], severityLevels: ['error'] },
        url: '/logs/alerts/alert-1',
    },
})

const endpointFailure = makeSignal({
    source_product: 'endpoints',
    source_type: 'endpoint_execution_failed',
    source_id: 'ep-1',
    content: 'The folder listing endpoint timed out.',
    extra: {
        endpoint_name: 'folder_listing',
        endpoint_version: 4,
        materialized: true,
        saved_query_id: null,
        error_class: 'QueryTimeout',
        error_message: 'Query exceeded the 60s limit.',
    },
})

const ciFlakyCheck = makeSignal({
    source_product: 'engineering_analytics',
    source_type: 'ci_flaky_check',
    source_id: 'ci-1',
    content: 'The upload integration test flips between pass and fail on retry.',
    extra: {
        repo_owner: 'example',
        repo_name: 'app',
        workflow_name: 'CI',
        job_name: 'integration-tests',
        run_id: 1,
        head_sha: 'abc123',
        failed_attempt: 1,
        passed_attempt: 2,
        flaky_count: 6,
        window_days: 7,
    },
})

const anomalyInvestigation = makeSignal({
    source_product: 'analytics',
    source_type: 'anomaly_investigation',
    source_id: 'anomaly-1',
    content: 'Upload completions dropped 40% day over day.',
    extra: {
        alert_id: 'alert-2',
        alert_name: 'Upload completions',
        alert_check_id: 'check-1',
        insight_id: 'insight-1',
        detector_type: 'z_score',
        verdict: 'true_positive',
        url: '/alerts/alert-2',
        insight_name: 'Upload completions',
        insight_short_id: 'abc123',
    },
})

const meta: Meta = {
    title: 'Scenes-App/Inbox/Signal cards',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-06-11',
        // The evidence links and previews are part of the redesign.
        featureFlags: { [FEATURE_FLAGS.INBOX_REDESIGN]: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/exports/:exportId/content/': (req) =>
                    pngResponse(
                        ['103', '104'].includes(String(req.params.exportId)) ? ATTACHMENT_PNG : RECORDING_PREVIEW_PNG
                    ),
            },
            post: {
                '/api/environments/:id/session_recordings/batch_check_exists': () => [
                    200,
                    { results: { 'sess-1': true, 'sess-2': true } },
                ],
                '/api/projects/:id/session_recordings/batch_check_exists': () => [
                    200,
                    { results: { 'sess-1': true, 'sess-2': true } },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj

/** Same width as the evidence rail in the report detail, where these cards render. */
function Rail({ signals }: { signals: SignalNode[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-3 w-[26rem]">
            {signals.map((signal) => (
                <SignalCard key={signal.signal_id} signal={signal} />
            ))}
        </div>
    )
}

export const RecordingPreviews: Story = {
    render: () => <Rail signals={[sessionProblem, scannerFinding, sessionProblemWithoutScreenshot]} />,
}

export const TicketAttachments: Story = {
    render: () => <Rail signals={[conversationsTicket]} />,
}

export const GenericFallbacks: Story = {
    render: () => <Rail signals={[genericWithEntityLink, genericWithExternalLink, genericWithoutLink]} />,
}

/** The stack trace fence in the signal content is cut to three lines instead of filling the rail. */
export const ErrorTrackingStackTrace: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/error_tracking/issues/:issue_id/': () => [
                    200,
                    {
                        id: 'issue-3',
                        name: 'RequestEntityTooLarge',
                        description: 'upload chunk exceeds 10 MB',
                        assignee: null,
                        status: 'active',
                        first_seen: '2026-06-08T09:30:00Z',
                        external_issues: [],
                    },
                ],
            },
            post: {
                '/api/environments/:team_id/query/ErrorTrackingQuery/': () => [
                    200,
                    {
                        results: [
                            {
                                first_seen: '2026-06-08T09:30:00Z',
                                last_seen: BASE_DATE,
                                aggregations: {
                                    occurrences: 12,
                                    sessions: 8,
                                    users: 6,
                                    volume_buckets: [
                                        { label: '2026-06-08T00:00:00Z', value: 2 },
                                        { label: '2026-06-09T00:00:00Z', value: 4 },
                                        { label: '2026-06-10T00:00:00Z', value: 6 },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            },
        }),
    ],
    render: () => <Rail signals={[errorTrackingIssueWithStackTrace]} />,
}

/** One card per source with a dedicated renderer, so a layout change to any of them shows up here. */
export const AllSources: Story = {
    render: () => (
        <Rail
            signals={[
                scoutFinding,
                scannerFinding,
                sessionProblem,
                errorTrackingIssue,
                healthCheck,
                conversationsTicket,
                githubIssue,
                linearIssue,
                zendeskTicket,
                pgAnalyzeIssue,
                logsAlert,
                endpointFailure,
                ciFlakyCheck,
                anomalyInvestigation,
            ]}
        />
    ),
}
