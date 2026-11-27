import '@testing-library/jest-dom'

import { fireEvent, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { integrationsList } from 'products/integrations/frontend/generated/api'
import { hogFlowsEmailSendingSuspensionRetrieve } from 'products/workflows/frontend/generated/api'

import { MessageAudience, MessageAudienceDestination, captureMessageAudienceClicked } from './messageAudience'
import { MessageAudienceWarning, loadMessageAudienceWarnings, openMessageAudience } from './messageAudienceWarnings'

jest.mock('products/cohorts/frontend/generated/api', () => ({ cohortsRetrieve: jest.fn() }))
jest.mock('products/integrations/frontend/generated/api', () => ({ integrationsList: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({ hogFlowsEmailSendingSuspensionRetrieve: jest.fn() }))

const SUSPENDED: MessageAudienceWarning = {
    kind: 'sending_suspended',
    message: 'Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.',
}
const NO_SENDER: MessageAudienceWarning = { kind: 'no_sender', message: 'Set up an email sender before sending' }
const UNVERIFIED: MessageAudienceWarning = {
    kind: 'unverified_sender',
    message: "Verify the sender's domain before sending",
}
const LIST_MATCHING: MessageAudienceWarning = {
    kind: 'cohort_not_ready',
    message: '"Signups" is still matching people. You can launch when it finishes.',
}

const verified = { kind: 'email', config: { verified: true } }
const unverified = { kind: 'email', config: { verified: false } }
const matchingList = { name: 'Signups', is_static: true, is_calculating: true, last_calculation: null }
const audience: MessageAudience = {
    source: 'cohort',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

describe('loadMessageAudienceWarnings', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each<{
        case: string
        destination: MessageAudienceDestination
        suspended?: boolean
        senders?: object[] | Error
        morePages?: boolean
        cohort?: object | Error
        expected: MessageAudienceWarning[]
    }>([
        { case: 'nothing wrong', destination: 'broadcast', expected: [] },
        {
            case: 'no sender while sending is suspended',
            destination: 'broadcast',
            suspended: true,
            senders: [],
            expected: [SUSPENDED, NO_SENDER],
        },
        {
            case: 'only unverified senders',
            destination: 'broadcast',
            senders: [unverified],
            expected: [UNVERIFIED],
        },
        {
            case: 'unverified senders on the first of several pages',
            destination: 'broadcast',
            senders: [unverified],
            morePages: true,
            expected: [],
        },
        { case: 'a list still matching', destination: 'broadcast', cohort: matchingList, expected: [LIST_MATCHING] },
        { case: 'a workflow, which ignores the list', destination: 'workflow', cohort: matchingList, expected: [] },
        {
            case: 'checks that fail',
            destination: 'broadcast',
            senders: new Error('down'),
            cohort: new Error('down'),
            expected: [],
        },
    ])(
        'reports $case',
        async ({ destination, suspended = false, senders = [verified], morePages, cohort, expected }) => {
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
                email_sending_suspended: suspended,
            } as never)
            jest.mocked(integrationsList).mockImplementation(async () => {
                if (senders instanceof Error) {
                    throw senders
                }
                return { count: senders.length, results: senders, next: morePages ? 'page-2' : null } as never
            })
            jest.mocked(cohortsRetrieve).mockImplementation(async () => {
                if (cohort instanceof Error) {
                    throw cohort
                }
                return (cohort ?? { name: 'Signups', is_static: true, is_calculating: false }) as never
            })

            expect(await loadMessageAudienceWarnings(audience, destination)).toEqual(expected)
        }
    )

    it('gives up on a check that never answers', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockReturnValue(new Promise(() => {}))
            jest.mocked(integrationsList).mockResolvedValue({ count: 0, results: [] } as never)

            const warnings = loadMessageAudienceWarnings(audience, 'workflow')
            await jest.advanceTimersByTimeAsync(5000)

            expect(await warnings).toEqual([NO_SENDER])
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        {
            case: 'a sender problem',
            suspended: false,
            kinds: ['no_sender'],
            secondary: 'Set up email',
            landsOn: urls.workflows('channels'),
        },
        {
            case: 'only a suspension',
            suspended: true,
            senders: [verified],
            kinds: ['sending_suspended'],
            secondary: 'Cancel',
            landsOn: '/start',
        },
    ])(
        'reports the warnings it shows for $case, and $secondary takes the person to $landsOn',
        async ({ suspended, senders = [], kinds, secondary, landsOn }) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            try {
                router.actions.push('/start')
                jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
                    email_sending_suspended: suspended,
                } as never)
                jest.mocked(integrationsList).mockResolvedValue({
                    count: senders.length,
                    results: senders,
                    next: null,
                } as never)

                captureMessageAudienceClicked('early_access', 'workflow')
                await openMessageAudience({ ...audience, source: 'early_access' }, 'workflow')

                const events = capture.mock.calls.map(([event, properties]) => ({ event, properties }))
                const [clicked, shown] = events
                expect(shown).toEqual({
                    event: 'message audience warnings shown',
                    properties: {
                        source: 'early_access',
                        destination: 'workflow',
                        attempt_id: clicked.properties?.attempt_id,
                        warnings: kinds,
                    },
                })
                fireEvent.click(await screen.findByText(secondary))
                await waitFor(() => expect(screen.queryByText('Before you send')).not.toBeInTheDocument())
                expect(router.values.location.pathname.endsWith(landsOn)).toBe(true)
            } finally {
                capture.mockRestore()
            }
        }
    )
})
