import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { integrationsList } from 'products/integrations/frontend/generated/api'
import { hogFlowsEmailSendingSuspensionRetrieve } from 'products/workflows/frontend/generated/api'

import { MessageAudience, MessageAudienceDestination } from './messageAudience'
import { loadMessageAudienceWarnings, openMessageAudience } from './messageAudienceWarnings'

jest.mock('products/cohorts/frontend/generated/api', () => ({ cohortsRetrieve: jest.fn() }))
jest.mock('products/integrations/frontend/generated/api', () => ({ integrationsList: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({ hogFlowsEmailSendingSuspensionRetrieve: jest.fn() }))

const SUSPENDED = 'Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.'
const LIST_MATCHING = '"Signups" is still matching people. You can launch when it finishes.'

const verified = { kind: 'email', config: { verified: true } }
const unverified = { kind: 'email', config: { verified: false } }
const sandbox = { kind: 'email', config: { provider: 'sandbox', verified: true } }
const matchingList = { name: 'Signups', is_static: true, is_calculating: true, last_calculation: null }
const audience: MessageAudience = {
    source: 'cohort',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

describe('messageAudienceWarnings', () => {
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
        expected: string[]
    }>([
        { case: 'nothing wrong', destination: 'broadcast', expected: [] },
        {
            case: 'no sender while sending is suspended',
            destination: 'broadcast',
            suspended: true,
            senders: [],
            expected: [SUSPENDED, 'Set up an email sender before sending'],
        },
        {
            case: 'only unverified senders',
            destination: 'broadcast',
            senders: [unverified],
            expected: ["Verify the sender's domain before sending"],
        },
        ...(['broadcast', 'workflow'] as const).map((destination) => ({
            case: `only the sandbox sender (${destination})`,
            destination,
            senders: [sandbox],
            expected: [
                'The sandbox sender only delivers to verified members of your organization. Set up your own email sender to reach this audience.',
            ],
        })),
        {
            case: 'an unverified own sender beside the sandbox sender',
            destination: 'broadcast',
            senders: [sandbox, unverified],
            expected: ["Verify the sender's domain before sending"],
        },
        {
            case: 'a verified own sender beside the sandbox sender',
            destination: 'broadcast',
            senders: [sandbox, verified],
            expected: [],
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

            expect(await warnings).toEqual(['Set up an email sender before sending'])
        } finally {
            jest.useRealTimers()
        }
    })

    it('offers to set up email when only the sandbox sender exists', async () => {
        jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
            email_sending_suspended: false,
        } as never)
        jest.mocked(integrationsList).mockResolvedValue({ count: 1, results: [sandbox], next: null } as never)
        const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})

        await openMessageAudience(audience, 'workflow')
        const secondaryButton = openDialog.mock.calls[0][0].secondaryButton
        secondaryButton?.onClick?.({} as never)

        expect(secondaryButton?.children).toEqual('Set up email')
        expect(router.values.location.pathname).toContain(urls.workflows('channels'))
    })
})
