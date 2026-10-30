import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

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
    it.each<[HogflowTestResult['emailSendResult'], boolean]>([
        [{ status: 'accepted' }, true],
        [{ status: 'skipped', reason: 'The recipient has no reachable mail servers.' }, false],
        [{ status: 'failed', reason: 'The provider refused the message.' }, false],
        [undefined, false],
    ])('requires provider acceptance before confirming a test send: %j', async (emailSendResult, sent) => {
        const warning = jest.spyOn(lemonToast, 'warning')
        const error = jest.spyOn(lemonToast, 'error')
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
        if (emailSendResult?.status === 'skipped') {
            expect(warning).toHaveBeenCalledWith('The recipient has no reachable mail servers.')
        } else if (!sent) {
            expect(error).toHaveBeenCalledWith(
                emailSendResult?.reason ??
                    'Could not confirm the test email was sent. Check the recipient and try again.'
            )
        }
        warning.mockRestore()
        error.mockRestore()
    })
})
