import { IntegrationType } from '~/types'

import { MessageAudienceCohort, messageAudienceButtonLabel, messageAudienceReadiness } from './messageAudienceReadiness'

const verifiedSender = { id: 1, kind: 'email', config: { verified: true } } as unknown as IntegrationType
const unverifiedSender = { id: 2, kind: 'email', config: { verified: false } } as unknown as IntegrationType
const size = (reach: number, withEmail: number, limit = 100): { reach: number; withEmail: number; limit: number } => ({
    reach,
    withEmail,
    limit,
})
const cohort = (overrides: Partial<MessageAudienceCohort>): MessageAudienceCohort => ({
    name: 'Beta testers',
    isStatic: false,
    pending: false,
    failed: false,
    ...overrides,
})

describe('messageAudienceReadiness', () => {
    it.each([
        {
            case: 'a reachable audience',
            input: { size: size(12, 10) },
            expected: { countState: 'ready', count: 10, disabledReason: null, warnings: [] },
            label: 'Email 10 people',
        },
        {
            case: 'one person',
            input: { size: size(1, 1) },
            expected: { countState: 'ready', count: 1, disabledReason: null, warnings: [] },
            label: 'Email 1 person',
        },
        {
            case: 'nobody in the audience',
            input: { size: size(0, 0) },
            expected: { count: 0, disabledReason: 'No one is in this audience yet' },
            label: 'Email these people',
        },
        {
            case: 'nobody with an email address',
            input: { size: size(3, 0) },
            expected: { count: 0, disabledReason: 'No one in this audience has an email address' },
            label: 'Email these people',
        },
        {
            case: 'an audience over the limit',
            input: { size: size(31, 31, 20) },
            expected: {
                count: 31,
                disabledReason: null,
                warnings: [
                    'This project can send a broadcast to up to 20 people right now. This audience has 31 people. Narrow it before sending.',
                ],
            },
            label: 'Email 31 people',
        },
        {
            case: 'a count that is still loading',
            input: { size: null, sizeLoading: true },
            expected: { countState: 'loading', count: null, disabledReason: null },
            label: 'Email these people',
        },
        {
            case: 'a count that failed',
            input: { size: null, sizeFailed: true },
            expected: { countState: 'failed', count: null, disabledReason: null },
            label: 'Email these people',
        },
        {
            case: 'a cohort still calculating, whose count is not final',
            input: { size: size(0, 0), cohorts: [cohort({ pending: true })] },
            expected: {
                countState: 'pending',
                count: null,
                disabledReason: null,
                warnings: [
                    '"Beta testers" is still calculating who\'s in it. You can write the email now and send it once it finishes.',
                ],
            },
            label: 'Email these people',
        },
        {
            case: 'no email sender',
            input: { size: size(5, 5), integrations: [] },
            expected: { disabledReason: null, warnings: ['Set up an email sender before sending'] },
            label: 'Email 5 people',
        },
        {
            case: 'only unverified senders, with sending suspended',
            input: { size: size(5, 5), integrations: [unverifiedSender], emailSendingSuspended: true },
            expected: {
                warnings: [
                    'Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.',
                    "Verify the sender's domain before sending",
                ],
            },
            label: 'Email 5 people',
        },
    ])('reports $case', ({ input, expected, label }) => {
        const readiness = messageAudienceReadiness({
            sizeLoading: false,
            sizeFailed: false,
            cohorts: [],
            integrations: [verifiedSender],
            emailSendingSuspended: false,
            ...input,
        })
        expect(readiness).toMatchObject(expected)
        expect(messageAudienceButtonLabel(readiness, 'Email these people').replace(/\s/g, ' ')).toEqual(label)
    })
})
