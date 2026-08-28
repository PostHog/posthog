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
