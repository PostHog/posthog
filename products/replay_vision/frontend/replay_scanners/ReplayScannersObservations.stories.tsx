import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import { LONG, LONG_INACTIVE, summary as timelineSummary } from '../__mocks__/recordingTimelineObservations'
import { replayScannersStoryConfig } from '../__mocks__/replayScannersStoryConfig'
import {
    classifierOverviewScanner,
    classifierOverviewStats,
    monitorOverviewScanner,
    monitorOverviewStats,
    observation,
    observationDetail,
    observations,
    overviewDecorator,
    scorerOverviewScanner,
    scorerOverviewStats,
    summarizerScanner,
} from '../__mocks__/replayScannersStoryFixtures'
import type { ObservationStatsApi, ReplayObservationApi, ReplayScannerApi } from '../generated/api.schemas'

const meta: Meta = {
    ...replayScannersStoryConfig,
    component: App,
    title: 'Scenes-App/Replay Vision',
}
export default meta

const MONITOR_DETAIL_PROMPT = [
    'Did the user struggle to complete checkout?',
    '',
    'Answer yes if the user shows clear friction on the cart, shipping, or payment steps. Count any of these as friction:',
    '- Entering a coupon or gift card code more than once after a validation error',
    '- Resubmitting the payment form after an error message',
    '- Moving back and forth between the cart and the payment step without completing the order',
    '- Rage-clicking a disabled or unresponsive button, such as Place order while shipping rates load',
    '- Leaving the site within a minute of seeing an error message',
    '',
    'Answer no if the user completes the order without going back, or browses the cart and leaves without trying to pay. Leaving without paying is not struggling on its own.',
    '',
    'Answer inconclusive if the recording ends before the user reaches a decision, or if most of the checkout is masked.',
    '',
    'Ignore sessions from internal staff accounts and sessions shorter than ten seconds.',
].join('\n')

const CLASSIFIER_DETAIL_PROMPT = [
    'Tag this session with every friction pattern that clearly appears in it. A session can have several tags or none.',
    '',
    '- rage-click: three or more fast clicks on the same element when it does not respond',
    '- dead-end: the user reaches a page with no obvious next step and leaves or goes back',
    '- slow-load: a page or component takes more than about five seconds to show content while the user waits',
    '- form-error: a validation or submit error appears on a form the user is filling in',
    '',
    'Only tag what you can see in the recording, and leave out borderline cases. When a clear friction pattern fits none of these tags, add a short freeform tag in kebab-case instead of forcing it into the closest match.',
].join('\n')

const SCORER_DETAIL_PROMPT = [
    'Score how strong the buying intent in this session is, from 0 to 10.',
    '',
    'Score high (8 to 10) when the user takes steps that only make sense before paying: comparing plans on the pricing page, opening billing settings, entering payment details, or inviting teammates to the workspace.',
    '',
    'Score in the middle (4 to 7) when the user explores the product in depth, for example building a dashboard or reading the docs for several minutes, but never goes near pricing or billing.',
    '',
    'Score low (0 to 3) for short visits, sessions that bounce from the landing page, or sessions spent mostly in account settings unrelated to billing.',
    '',
    'Base the score only on what happens in this recording, not on how old the account is. Give a short label that names the level of intent.',
].join('\n')

// A monitor observation, so the detail page renders the prompt row and the reasoning card that a
// summarizer hides. The prompt and reasoning are long on purpose, so both clips show. Other stories
// keep the one-paragraph reasoning most scans produce.
const monitorObservationDetail = observation({
    prompt_question: 'Did the user struggle to complete checkout?',
    prompt_valence: 'bad',
    id: '00000000-0000-0000-0000-0000000000d2',
    session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d11',
    recording_subject_email: 'bob@example.com',
    distinct_id: 'user_2m1x9d',
    previous_observation_id: '00000000-0000-0000-0000-0000000000b1',
    next_observation_id: '00000000-0000-0000-0000-0000000000b4',
    scanner_snapshot: {
        name: 'Confused checkout',
        scanner_type: 'monitor',
        scanner_version: 3,
        model: 'gemini-3.8-flash',
        provider: 'google',
        emits_signals: true,
        scanner_config: {
            prompt: MONITOR_DETAIL_PROMPT,
            allow_inconclusive: true,
        },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.82,
            verdict: 'yes',
            reasoning: [
                'The user reached the cart about a minute into the session and moved to checkout with two items. On the payment step they entered the coupon code SPRING20 and got the error "This code is not valid for items in your cart." They cleared the field and entered it again with the same result, then tried it in lowercase, which failed the same way.',
                '',
                'After the third failure they went back to the cart, removed one item, and returned to payment, which looks like an attempt to make the coupon apply. It still failed. They then filled in the card details and pressed Place order. The page showed a spinner for several seconds and then "Payment could not be processed. Please try again." They submitted the form once more, got the same message, and closed the tab about twenty seconds later.',
                '',
                'This matches three of the friction signals in the prompt: repeated coupon retries after a validation error, going back from payment to the cart, and resubmitting the payment form after an error. The session is not from a staff account and is well over ten seconds long.',
                '',
                'Confidence is below certain because the card fields are masked, so the recording does not show whether the second payment error came from the same input as the first.',
            ].join('\n'),
        },
        signals_count: 1,
    },
})

export const ScannerObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=observations` },
}

// The shared list rows rebuilt for another scanner type: same sessions, people and statuses, with each
// succeeded row carrying that type's output. The failed row keeps its null result.
const observationsFor = (
    scannerResponse: ReplayScannerApi,
    outputs: Record<string, unknown>[]
): typeof observations => {
    let next = 0
    return {
        ...observations,
        results: observations.results.map((row) => ({
            ...row,
            scanner_id: scannerResponse.id,
            scanner_snapshot: {
                ...row.scanner_snapshot,
                name: scannerResponse.name,
                scanner_type: scannerResponse.scanner_type,
                scanner_config: scannerResponse.scanner_config,
            },
            scanner_result: row.scanner_result
                ? {
                      ...row.scanner_result,
                      model_output: { scanner_type: scannerResponse.scanner_type, ...outputs[next++ % outputs.length] },
                  }
                : null,
        })) as ReplayObservationApi[],
    }
}

const observationsTabDecorator = (
    scannerResponse: ReplayScannerApi,
    stats: ObservationStatsApi,
    outputs: Record<string, unknown>[]
): ReturnType<typeof mswDecorator>[] => [
    overviewDecorator(scannerResponse, stats),
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/:id/observations/': observationsFor(scannerResponse, outputs),
        },
    }),
]

export const MonitorObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(monitorOverviewScanner.id)}?tab=observations` },
    decorators: observationsTabDecorator(monitorOverviewScanner, monitorOverviewStats, [
        {
            verdict: 'yes',
            confidence: 0.91,
            reasoning: 'Retried the payment form twice and left the page before completing the order.',
        },
        {
            verdict: 'no',
            confidence: 0.84,
            reasoning: 'Moved through checkout in under a minute without errors or backtracking.',
        },
        {
            verdict: 'inconclusive',
            confidence: 0.4,
            reasoning: 'The recording ends on the shipping step, so the outcome is unclear.',
        },
    ]),
}

export const ClassifierObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(classifierOverviewScanner.id)}?tab=observations` },
    decorators: observationsTabDecorator(classifierOverviewScanner, classifierOverviewStats, [
        {
            tags: ['rage-click', 'slow-load'],
            tags_freeform: ['coupon-confusion'],
            confidence: 0.88,
            reasoning: 'Clicked the disabled submit button repeatedly while the shipping rates loaded.',
        },
        {
            tags: ['dead-end'],
            tags_freeform: [],
            confidence: 0.79,
            reasoning: 'Opened the returns page from the footer and found no way back to the cart.',
        },
        { tags: [], tags_freeform: [], confidence: 0.72, reasoning: 'A short browse with no friction.' },
    ]),
}

export const ScorerObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(scorerOverviewScanner.id)}?tab=observations` },
    decorators: observationsTabDecorator(scorerOverviewScanner, scorerOverviewStats, [
        { score: 8.5, confidence: 0.86, reasoning: 'Compared plans, opened billing and invited a teammate.' },
        { score: 2, confidence: 0.8, reasoning: 'Bounced from the pricing page after a few seconds.' },
        { score: 5.5, confidence: 0.7, reasoning: 'Read the docs at length but never started a trial.' },
    ]),
}

const observationDetailFor = (
    scannerResponse: ReplayScannerApi,
    id: string,
    output: Record<string, unknown>,
    promptQuestion: string | null = null
): ReplayObservationApi =>
    observation({
        id,
        prompt_question: promptQuestion,
        scanner_id: scannerResponse.id,
        recording_subject_email: 'bob@example.com',
        distinct_id: 'user_2m1x9d',
        previous_observation_id: '00000000-0000-0000-0000-0000000000b1',
        next_observation_id: '00000000-0000-0000-0000-0000000000b4',
        scanner_snapshot: {
            ...observation().scanner_snapshot!,
            name: scannerResponse.name,
            scanner_type: scannerResponse.scanner_type,
            scanner_config: scannerResponse.scanner_config,
        },
        scanner_result: {
            model_output: { scanner_type: scannerResponse.scanner_type, ...output },
            signals_count: 0,
        },
    })

const classifierObservationDetail = observationDetailFor(
    {
        ...classifierOverviewScanner,
        scanner_config: {
            prompt: CLASSIFIER_DETAIL_PROMPT,
            tags: ['rage-click', 'dead-end', 'slow-load', 'form-error'],
            multi_label: true,
            allow_freeform_tags: true,
        },
    },
    '00000000-0000-0000-0000-0000000000d4',
    {
        tags: ['rage-click', 'slow-load'],
        tags_freeform: ['coupon-confusion'],
        confidence: 0.64,
        reasoning:
            'On the shipping step the user pressed the disabled Continue to payment button seven times in about four seconds while the rates were still loading, and the rates took roughly nine seconds to appear, so the step shows both rage-click and slow-load. On payment they entered a coupon code twice and got "Code not recognized" both times, which is tagged coupon-confusion rather than form-error because the form itself submitted fine. There is no dead-end: the user always had a next step and placed the order.',
    },
    'Which friction patterns appear in this session?'
)

const scorerObservationDetail: ReplayObservationApi = {
    ...observationDetailFor(
        {
            ...scorerOverviewScanner,
            scanner_config: { prompt: SCORER_DETAIL_PROMPT, scale: { min: 0, max: 10, label: 'buying intent' } },
        },
        '00000000-0000-0000-0000-0000000000d5',
        {
            score: 8.5,
            label: 'buying intent',
            confidence: 0.41,
            reasoning:
                'The user spent about two minutes on the pricing page comparing the Growth and Enterprise plans, then opened the Billing tab and started to add a card before closing the form. Right after that they invited two teammates from the Members page. Looking at billing and then inviting a team puts this in the high band of the prompt, but not at the top, because the payment details were never saved and the rest of the session was spent back in the product.',
        },
        'How strong is the buying intent in this session?'
    ),
    prompt_valence: 'good',
}

const observationDetailStory = (detail: ReplayObservationApi): StoryObj => ({
    parameters: { pageUrl: urls.replayVisionObservation(detail.id) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/vision/observations/:id/': detail } })],
})

// A scan the model never finished, so the page leads with the failure and a retry instead of a result.
const failedObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d6',
    status: 'failed',
    error_reason: 'provider_transient:The model timed out before returning a result.',
    scanner_result: null,
})

export const ObservationDetailFailed: StoryObj = {
    ...observationDetailStory(failedObservationDetail),
    play: async ({ canvasElement }) => {
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="recording-play"]')).toBeVisible())
        // The floating player controls hide on a timer after mount, so wait for that to happen before the snapshot.
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="recording-play"]')).not.toBeVisible())
    },
}

// The session had no screen data to watch, so no model ran and a later retry may still succeed.
const notScannedObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d7',
    status: 'ineligible',
    error_reason: 'no_snapshots:The recording has no snapshot data yet.',
    scanner_result: null,
})

// A scan still in progress, so the page shows progress where the result goes.
const runningObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d8',
    status: 'running',
    error_reason: '',
    scanner_result: null,
    completed_at: null,
})

export const ObservationDetailNotScanned: StoryObj = observationDetailStory(notScannedObservationDetail)

export const ObservationDetailRunning: StoryObj = {
    ...observationDetailStory(runningObservationDetail),
    // A running scan keeps its progress and status spinners going, so the page never settles for a snapshot.
    tags: ['test-skip'],
}

// The observation outlived its recording, so the player's place explains why and shows the saved frame.
export const ObservationDetailRecordingExpired: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(monitorObservationDetail.id) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/observations/:id/': monitorObservationDetail,
                '/api/environments/:team_id/session_recordings/:id': () => [404, { detail: 'Not found.' }],
            },
        }),
    ],
}

export const ObservationDetailClassifier: StoryObj = observationDetailStory(classifierObservationDetail)

export const ObservationDetailScorer: StoryObj = observationDetailStory(scorerObservationDetail)

export const ObservationDetail: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(observationDetail.id) },
}

// The only story covering the collapsed prompt row and the pinned session properties card.
export const ObservationDetailMonitor: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(monitorObservationDetail.id) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/observations/:id/': monitorObservationDetail,
            },
        }),
    ],
}

// The monitor allows inconclusive answers, and this one ran out of recording before the user decided.
const inconclusiveObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d9',
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.58,
            verdict: 'inconclusive',
            reasoning:
                'The user added two items to the cart and opened the payment step, where the card fields are masked. The recording ends about ten seconds later with the page still loading, so it does not show whether the payment went through or whether the user gave up. There is no retry, error message or backtracking before the recording stops.',
        },
        signals_count: 0,
    },
})

export const ObservationDetailMonitorInconclusive: StoryObj = observationDetailStory(inconclusiveObservationDetail)

// The Session Replay "Summarize" button mints an inline scanner with the session summary template's prompt, so
// its observations carry that template's written question.
const summarizeButtonObservationDetail = observation({
    id: '00000000-0000-0000-0000-0000000000da',
    scanner_id: '00000000-0000-0000-0000-00000000001a',
    scanner_origin: 'inline',
    recording_subject_email: 'bob@example.com',
    distinct_id: 'user_2m1x9d',
    prompt_question: 'What did the user do in this session?',
    scanner_snapshot: {
        ...observation().scanner_snapshot!,
        name: '',
        scanner_config: {
            prompt: "Summarize what the user did in this session: which pages they visited, what they tried to accomplish, and any notable moments like errors, confusion, or successful completions. Be concrete and don't speculate.",
            length: 'medium',
        },
    },
})

export const ObservationDetailSummarizeButton: StoryObj = observationDetailStory(summarizeButtonObservationDetail)

// A one-off scan asked through PostHog AI or MCP: an inline scanner with its own prompt and no written question.
const inlineScanObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000db',
    scanner_id: '00000000-0000-0000-0000-00000000001b',
    scanner_origin: 'inline',
    prompt_question: null,
    previous_observation_id: null,
    next_observation_id: null,
    scanner_snapshot: {
        ...monitorObservationDetail.scanner_snapshot!,
        name: '',
        scanner_config: { prompt: 'Did the user open the pricing page and leave without upgrading?' },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.9,
            verdict: 'yes',
            reasoning:
                'The user opened the pricing page twice, expanded the plan comparison, and left the app from there both times without starting a checkout.',
        },
        signals_count: 0,
    },
})

export const ObservationDetailInlineScan: StoryObj = observationDetailStory(inlineScanObservationDetail)

// A summary that carries chapters, so the result card gains Summary and Timeline tabs.
const timelineObservationDetail = (() => {
    const withChapters = timelineSummary({ chapters: LONG, inactive: LONG_INACTIVE })
    const output = withChapters.scanner_result!.model_output as Record<string, unknown>
    return observation({
        ...observationDetail,
        id: '00000000-0000-0000-0000-0000000000d9',
        scanner_result: {
            ...observationDetail.scanner_result!,
            model_output: {
                ...(observationDetail.scanner_result!.model_output as Record<string, unknown>),
                chapters: output.chapters,
                inactive_periods: output.inactive_periods,
            },
        } as ReplayObservationApi['scanner_result'],
        media: withChapters.media,
    })
})()

export const ObservationDetailSummaryWithTimeline: StoryObj = observationDetailStory(timelineObservationDetail)

// The timeline tab on an hour-long recording, the only story where the rail scrolls inside the card.
export const ObservationDetailTimeline: StoryObj = {
    ...observationDetailStory(timelineObservationDetail),
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Timeline'))
        await within(canvasElement).findByText('Session start')
    },
}
