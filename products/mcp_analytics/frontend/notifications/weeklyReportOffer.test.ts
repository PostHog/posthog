import { ApiError } from 'lib/api-error'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import {
    createErrorMessage,
    createMayHaveSucceeded,
    resolveWeeklyReportOffer,
    WeeklyReportOfferInputs,
} from './weeklyReportOffer'

const SAVED = { id: 7, enabled: true } as SubscriptionApi
const DISABLED = { id: 8, enabled: false } as SubscriptionApi

const ELIGIBLE: WeeklyReportOfferInputs = {
    isCloudOrDev: true,
    aiFlagEnabled: true,
    aiConsentApproved: true,
    userEmail: 'me@example.com',
    reports: [],
    submission: { status: 'idle' },
}

describe('weeklyReportOffer', () => {
    it.each<[string, Partial<WeeklyReportOfferInputs>, unknown]>([
        ['is ready when nothing blocks it', {}, { state: 'ready', email: 'me@example.com' }],
        ['loads until preflight answers', { isCloudOrDev: undefined }, { state: 'loading' }],
        ['loads until the flags arrive', { aiFlagEnabled: null }, { state: 'loading' }],
        ['loads until the organization arrives', { aiConsentApproved: null }, { state: 'loading' }],
        ['loads until the user arrives', { userEmail: null }, { state: 'loading' }],
        ['loads until the reports arrive', { reports: 'loading' }, { state: 'loading' }],
        ['loads before it hides', { isCloudOrDev: false, reports: 'loading' }, { state: 'loading' }],
        ['hides when self-hosted', { isCloudOrDev: false }, { state: 'hidden', reason: 'self-hosted' }],
        ['hides when the flag is off', { aiFlagEnabled: false }, { state: 'hidden', reason: 'not-enabled' }],
        [
            'hides on the flag before it asks for consent',
            { aiFlagEnabled: false, aiConsentApproved: false },
            { state: 'hidden', reason: 'not-enabled' },
        ],
        [
            'hides when the project already has an MCP report',
            { reports: [SAVED] },
            { state: 'hidden', reason: 'has-report' },
        ],
        [
            'hides when the report list is unknown',
            { reports: 'unknown' },
            { state: 'hidden', reason: 'unknown-reports' },
        ],
        [
            'hides for an existing report before it asks for consent',
            { reports: [SAVED], aiConsentApproved: false },
            { state: 'hidden', reason: 'has-report' },
        ],
        ['asks for consent', { aiConsentApproved: false }, { state: 'needs-ai-consent', email: 'me@example.com' }],
        [
            'carries the server message when creating failed',
            { submission: { status: 'failed', message: 'Your plan is limited to 5 subscriptions.' } },
            { state: 'failed', email: 'me@example.com', message: 'Your plan is limited to 5 subscriptions.' },
        ],
        [
            'asks for consent again when creating failed and consent is gone',
            { aiConsentApproved: false, submission: { status: 'failed', message: 'nope' } },
            { state: 'needs-ai-consent', email: 'me@example.com' },
        ],
        ['is creating', { submission: { status: 'creating' } }, { state: 'creating', email: 'me@example.com' }],
        [
            'keeps creating while the report list reloads',
            { reports: 'loading', submission: { status: 'creating' } },
            { state: 'creating', email: 'me@example.com' },
        ],
        [
            'ignores a disabled report, which delivers nothing',
            { reports: [DISABLED] },
            { state: 'ready', email: 'me@example.com' },
        ],
        [
            'hides when an enabled report sits beside a disabled one',
            { reports: [DISABLED, SAVED] },
            { state: 'hidden', reason: 'has-report' },
        ],
        [
            'is created while the new report is in the list',
            { reports: [SAVED], submission: { status: 'created', report: SAVED } },
            { state: 'created', report: SAVED },
        ],
        [
            'is created while an unrelated enabled report sits beside the new one',
            {
                reports: [{ id: 9, enabled: true } as SubscriptionApi, SAVED],
                submission: { status: 'created', report: SAVED },
            },
            { state: 'created', report: SAVED },
        ],
        [
            'offers again after the created report is deleted',
            { reports: [], submission: { status: 'created', report: SAVED } },
            { state: 'ready', email: 'me@example.com' },
        ],
        [
            'offers again after the created report is disabled',
            { reports: [{ ...SAVED, enabled: false }], submission: { status: 'created', report: SAVED } },
            { state: 'ready', email: 'me@example.com' },
        ],
        [
            'hides after the created report is deleted and another one exists',
            {
                reports: [{ id: 9, enabled: true } as SubscriptionApi],
                submission: { status: 'created', report: SAVED },
            },
            { state: 'hidden', reason: 'has-report' },
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(resolveWeeklyReportOffer({ ...ELIGIBLE, ...overrides })).toEqual(expected)
    })

    it.each([
        [
            'the server detail',
            new ApiError('Bad Request', 400, undefined, { detail: 'Plan limit reached.' }),
            'Plan limit reached.',
        ],
        [
            'a server error without detail',
            new ApiError('Server Error', 500),
            "Couldn't create the report. Try again, or set it up from the Notifications tab.",
        ],
        [
            'a network failure',
            new TypeError('Failed to fetch'),
            "Couldn't create the report. Try again, or set it up from the Notifications tab.",
        ],
    ])('explains a rejection with %s', (_name, error, expected) => {
        expect(createErrorMessage(error)).toBe(expected)
    })

    it.each([
        ['the server refuses the request', new ApiError('Bad Request', 400), false],
        ['the plan limit is hit', new ApiError('Forbidden', 403), false],
        ['the server fails', new ApiError('Server Error', 500), true],
        ['a gateway times out', new ApiError('Gateway Timeout', 504), true],
        ['the network drops', new TypeError('Failed to fetch'), true],
    ])('knows whether a report may have been saved when %s', (_name, error, expected) => {
        expect(createMayHaveSucceeded(error)).toBe(expected)
    })
})
