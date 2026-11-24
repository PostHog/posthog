import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import posthog from 'posthog-js'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EmailDomainSetupRecordKindEnumApi } from 'products/integrations/frontend/generated/api.schemas'

import type { HogflowTestResult } from '../../Workflows/hogflows/steps/types'
import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { VerificationStep, emailDomainLogic } from './emailDomainLogic'
import { emailDomainSenderLogic } from './emailDomainSenderLogic'

const DOMAIN = 'mail.acme.com'

describe('emailDomainLogic', () => {
    let backend: FakeEmailDomainBackend
    let logic: ReturnType<typeof emailDomainLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        backend = new FakeEmailDomainBackend()
        backend.hostDnsAt('acme.com', 'cloudflare')
        backend.addSender({ email: `hello@${DOMAIN}` })
        useMocks(backend.mocks())
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    const turnOnSuggestions = (on: boolean): void => {
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: on,
        })
    }

    const testEmailResults = (capture: jest.SpyInstance): unknown[][] =>
        capture.mock.calls.filter(([event]) => event === 'email domain test email result')

    const mountAndLoad = async (id = '42'): Promise<void> => {
        logic = emailDomainLogic({ id })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
    }

    it('shows the domain step for a new sender', async () => {
        turnOnSuggestions(true)
        await mountAndLoad('new')
        expect(logic.values.phase).toBe('domain')
        expect(backend.requestsTo('integration_get')).toHaveLength(0)
        expect(backend.requestsTo('email_status')).toHaveLength(0)
        expect(backend.requestsTo('data_suggestions_generate')).toHaveLength(0)
    })

    it.each<[string, EmailDomainSetupRecordKindEnumApi[], string]>([
        ['an existing DMARC record', ['dmarc'], 'settings'],
        ['an existing apex SPF record', ['spf', 'dmarc'], 'settings'],
        ['a DKIM record', ['dkim', 'dmarc'], 'verifying'],
        ['the verification record', ['verification'], 'verifying'],
    ])('shows the %s phase when the first check finds %s', async (_, kinds, phase) => {
        backend.preexistingRecords(DOMAIN, kinds)
        await mountAndLoad()
        expect(logic.values.phase).toBe(phase)
    })

    it('shows the ready phase once the domain is verified', async () => {
        backend.verifyDomain(DOMAIN)
        await mountAndLoad()
        expect(logic.values.phase).toBe('ready')
        expect(logic.values.verificationSteps.map((step) => step.state)).toEqual(['done', 'done', 'done'])
    })

    it.each<[string, boolean, VerificationStep['state'][]]>([
        ['every record is published', true, ['done', 'done', 'active']],
        ['records are missing', false, ['done', 'stuck', 'todo']],
    ])('marks the records step after automatic checks stop when %s', async (_, publishAll, states) => {
        if (publishAll) {
            backend.publishRecords(DOMAIN)
        }
        await mountAndLoad()
        await jest.advanceTimersByTimeAsync(31 * 60_000)
        expect(logic.values.verificationSteps.map((step) => step.state)).toEqual(states)
    })

    it.each<[string, boolean, number]>([
        ['suggestions on', true, 1],
        ['suggestions off', false, 0],
    ])('preloads workflow suggestions once a domain is picked, with %s, and loads them once', async (_, on, loads) => {
        turnOnSuggestions(on)
        await mountAndLoad()
        expect(logic.values.phase).toBe('settings')
        expect(backend.requestsTo('data_suggestions_generate')).toHaveLength(loads)

        backend.publishRecords(DOMAIN)
        await jest.advanceTimersByTimeAsync(10_000)
        expect(logic.values.phase).toBe('verifying')
        backend.verifyDomain(DOMAIN)
        await jest.advanceTimersByTimeAsync(10_000)
        expect(logic.values.phase).toBe('ready')
        expect(backend.requestsTo('data_suggestions_generate')).toHaveLength(loads)
    })

    it('reloads only what failed when the person tries again', async () => {
        silenceKeaLoadersErrors()
        backend.failOnce('integration_get', { status: 500, body: { detail: 'Could not reach the email provider' } })
        await mountAndLoad()
        resumeKeaLoadersErrors()
        expect(logic.values.phase).toBe('unavailable')
        const statusChecks = backend.requestsTo('email_status').length

        logic.actions.retry()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.phase).toBe('settings')
        expect(backend.requestsTo('integration_get')).toHaveLength(2)
        expect(backend.requestsTo('email_status')).toHaveLength(statusChecks)
    })

    it('says the sender is gone, without an error toast, and drops it from the sender list when it was deleted', async () => {
        const error = jest.spyOn(lemonToast, 'error')
        integrationsLogic.mount()
        await jest.advanceTimersByTimeAsync(0)
        backend.removeSender(42)

        await mountAndLoad('42')

        expect(logic.values.phase).toBe('unavailable')
        expect(logic.values.senderMissing).toBe(true)
        expect(integrationsLogic.values.integrations?.map((integration) => integration.id)).not.toContain(42)
        expect(error).not.toHaveBeenCalled()
        error.mockRestore()
    })
    it.each<[HogflowTestResult['emailSendResult'], boolean, string | null]>([
        [{ status: 'accepted' }, true, null],
        [
            {
                status: 'skipped',
                reason: 'Skipping send: the recipient has no email address. Add a filter so only people with an email address reach this step.',
            },
            false,
            'missing_recipient',
        ],
        [
            {
                status: 'skipped',
                reason: 'Skipping send: me@acme.com is on the suppression list and no cc address can receive the email instead',
            },
            false,
            'suppressed_recipient',
        ],
        [
            {
                status: 'skipped',
                reason: 'Skipping send: our email provider paused sending for this project. Check the Reputation tab to see what to fix.',
            },
            false,
            'sending_suspended',
        ],
        [
            { status: 'skipped', reason: 'Recipient has opted out, skipping message delivery.' },
            false,
            'recipient_opted_out',
        ],
        [
            {
                status: 'skipped',
                reason: 'Skipping send: the domain "acme.com" has no reachable mail servers, so this message would hard bounce.',
            },
            false,
            'recipient_unreachable',
        ],
        [{ status: 'failed', reason: 'The provider refused the message.' }, false, 'other'],
        [
            { status: 'failed', reason: 'The selected email integration is not configured correctly' },
            false,
            'sender_misconfigured',
        ],
        [
            { status: 'failed', reason: 'The selected email integration domain is not verified' },
            false,
            'domain_not_verified',
        ],
        [
            {
                status: 'failed',
                reason: 'Failed to send email via SES: Email address is not verified. The following identities failed the check in region US-EAST-1: hello@mail.acme.com',
            },
            false,
            'provider_identity_not_verified',
        ],
        [
            { status: 'failed', reason: 'Failed to send email via SES: Sending paused for this account.' },
            false,
            'provider_sending_paused',
        ],
        [
            {
                status: 'failed',
                reason: 'Failed to send email via SES: SES did not answer before the send deadline. It may have sent the email, so it is not sent again.',
            },
            false,
            'provider_timeout',
        ],
        [{ status: 'failed', reason: 'Failed to send email via SES: Illegal address' }, false, 'provider_rejected'],
        [undefined, false, 'no_send_result'],
    ])(
        'requires provider acceptance before confirming a test send, and records the classified outcome: %j',
        async (emailSendResult, sent, reason) => {
            const warning = jest.spyOn(lemonToast, 'warning')
            const error = jest.spyOn(lemonToast, 'error')
            const capture = jest.spyOn(posthog, 'capture')
            const mocks = backend.mocks()
            useMocks({
                ...mocks,
                post: {
                    ...mocks.post,
                    '/api/environments/:team_id/hog_flows/:id/invocations/': () => ({
                        status: 'success',
                        nextActionId: 'exit_node',
                        emailSendResult,
                    }),
                },
            })
            await mountAndLoad()
            const sender = emailDomainSenderLogic({ id: '42' })
            sender.actions.sendTestEmail()
            await jest.advanceTimersByTimeAsync(0)
            expect(sender.values.testEmailSent).toBe(sent)
            expect(testEmailResults(capture)).toEqual([
                ['email domain test email result', { status: emailSendResult?.status ?? 'failed', reason }],
            ])
            if (emailSendResult?.status === 'skipped') {
                expect(warning).toHaveBeenCalledWith(emailSendResult.reason)
            } else if (!sent) {
                expect(error).toHaveBeenCalledWith(
                    emailSendResult?.reason ??
                        'Could not confirm the test email was sent. Check the recipient and try again.'
                )
            }
            warning.mockRestore()
            error.mockRestore()
            capture.mockRestore()
        }
    )

    it('records a failed test send when the request itself fails', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const mocks = backend.mocks()
        useMocks({
            ...mocks,
            post: {
                ...mocks.post,
                '/api/environments/:team_id/hog_flows/:id/invocations/': () => [500, { detail: 'Server error' }],
            },
        })
        await mountAndLoad()
        const sender = emailDomainSenderLogic({ id: '42' })
        sender.actions.sendTestEmail()
        await jest.advanceTimersByTimeAsync(0)
        expect(testEmailResults(capture)).toEqual([
            ['email domain test email result', { status: 'failed', reason: 'request_failed' }],
        ])
        capture.mockRestore()
    })

    it('records the test send result when the page closes before the provider answers', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        let answer: (result: HogflowTestResult) => void = () => {}
        const invocation = jest
            .spyOn(api.hogFlows, 'createTestInvocation')
            .mockReturnValue(new Promise((resolve) => (answer = resolve)))
        await mountAndLoad()
        emailDomainSenderLogic({ id: '42' }).actions.sendTestEmail()
        logic.unmount()
        answer({ status: 'success', nextActionId: 'exit_node', emailSendResult: { status: 'accepted' } })
        await jest.advanceTimersByTimeAsync(0)
        expect(testEmailResults(capture)).toEqual([
            ['email domain test email result', { status: 'accepted', reason: null }],
        ])
        invocation.mockRestore()
        capture.mockRestore()
    })
})
