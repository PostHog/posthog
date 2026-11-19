import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { emailDomainStatusLogic } from './emailDomainStatusLogic'

const DOMAIN = 'mail.acme.com'
const MINUTE = 60_000

const setDocumentHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('emailDomainStatusLogic', () => {
    let backend: FakeEmailDomainBackend
    let logic: ReturnType<typeof emailDomainStatusLogic.build>

    const statusChecks = (): number => backend.requestsTo('email_status').length

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
        setDocumentHidden(false)
        jest.useRealTimers()
    })

    const mountAndLoad = async (): Promise<void> => {
        logic = emailDomainStatusLogic({ id: '42' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
    }

    it('polls every 10 seconds for 5 minutes, then every 30 seconds, and stops after 30 minutes', async () => {
        await mountAndLoad()
        expect(statusChecks()).toBe(1)

        await jest.advanceTimersByTimeAsync(10_000)
        expect(statusChecks()).toBe(2)

        await jest.advanceTimersByTimeAsync(5 * MINUTE - 10_000)
        expect(statusChecks()).toBe(31)

        await jest.advanceTimersByTimeAsync(10_000)
        expect(statusChecks()).toBe(31)
        await jest.advanceTimersByTimeAsync(20_000)
        expect(statusChecks()).toBe(32)

        await jest.advanceTimersByTimeAsync(25 * MINUTE)
        expect(statusChecks()).toBe(81)
        expect(logic.values.pollingStopped).toBe(true)

        await jest.advanceTimersByTimeAsync(5 * MINUTE)
        expect(statusChecks()).toBe(81)
    })

    it.each([MINUTE, 31 * MINUTE])(
        'pauses polling for %s milliseconds hidden and resumes within the original deadline',
        async (hiddenDuration) => {
            await mountAndLoad()
            expect(statusChecks()).toBe(1)

            setDocumentHidden(true)
            await jest.advanceTimersByTimeAsync(hiddenDuration)
            expect(statusChecks()).toBe(1)

            setDocumentHidden(false)
            await jest.advanceTimersByTimeAsync(10_000)
            expect(statusChecks()).toBe(hiddenDuration < 30 * MINUTE ? 2 : 1)
            expect(logic.values.pollingStopped).toBe(hiddenDuration >= 30 * MINUTE)
        }
    )

    it('asks the provider to set the domain up again and restarts the schedule when the person checks again', async () => {
        await mountAndLoad()
        await jest.advanceTimersByTimeAsync(31 * MINUTE)
        expect(logic.values.pollingStopped).toBe(true)
        const checksBefore = statusChecks()

        logic.actions.checkAgain()
        await jest.advanceTimersByTimeAsync(0)
        expect(backend.requestsTo('email_verify')).toHaveLength(1)
        expect(backend.requestsTo('email_status').at(-1)?.url).toContain('refresh=true')
        expect(logic.values.pollingStopped).toBe(false)

        await jest.advanceTimersByTimeAsync(10_000)
        expect(statusChecks()).toBe(checksBefore + 2)
    })

    it.each([
        [500, true],
        [400, false],
        [403, false],
        [404, false],
    ])('marks the status failed when a check answers %s and keeps polling: %s', async (httpStatus, keepsPolling) => {
        backend.fail('email_status', { status: httpStatus, body: { detail: 'SES read failed' } })
        await mountAndLoad()
        expect(logic.values.statusUnavailable).toBe(true)
        expect(logic.values.status).toBeNull()

        await jest.advanceTimersByTimeAsync(10_000)
        expect(statusChecks()).toBe(keepsPolling ? 2 : 1)

        backend.recover('email_status')
        logic.actions.recheck()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.statusUnavailable).toBe(false)
        expect(logic.values.status?.status).toBe('pending')
    })

    it('keeps the last status and the progress, and keeps polling, when a later check fails', async () => {
        backend.publishRecords(DOMAIN)
        await mountAndLoad()
        expect(logic.values.status?.status).toBe('records_found')

        backend.fail('email_status', { status: 503, body: { code: 'ses_unavailable', detail: 'SES is down' } })
        await jest.advanceTimersByTimeAsync(10_000)
        expect(logic.values.statusUnavailable).toBe(false)
        expect(logic.values.status?.status).toBe('records_found')
        expect(logic.values.foundCount).toBe(logic.values.records.length)

        backend.recover('email_status')
        backend.verifyDomain(DOMAIN)
        await jest.advanceTimersByTimeAsync(10_000)
        expect(statusChecks()).toBe(3)
        expect(logic.values.status?.verified).toBe(true)
    })

    it('records a verification the provider reports through email verify, once', async () => {
        backend.verifyAtProviderOnly(DOMAIN)

        await mountAndLoad()

        expect(backend.requestsTo('email_verify')).toHaveLength(1)
        expect(logic.values.status?.verified).toBe(true)
        await jest.advanceTimersByTimeAsync(MINUTE)
        expect(backend.requestsTo('email_verify')).toHaveLength(1)
    })

    it('records the verification on a later poll when email verify fails once', async () => {
        backend.verifyAtProviderOnly(DOMAIN)
        backend.failOnce('email_verify', { status: 500, body: { detail: 'SES is down' } })

        await mountAndLoad()
        expect(logic.values.status?.verified).toBe(false)

        await jest.advanceTimersByTimeAsync(MINUTE)
        expect(backend.requestsTo('email_verify')).toHaveLength(2)
        expect(logic.values.status?.verified).toBe(true)
    })

    it('stops polling once the domain is verified and refreshes the channel list and the default sender', async () => {
        backend.verifyDomain(DOMAIN)
        await mountAndLoad()
        expect(logic.values.status?.verified).toBe(true)
        expect(backend.requestsTo('integration_list').length).toBeGreaterThan(0)
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeam'])

        await jest.advanceTimersByTimeAsync(MINUTE)
        expect(statusChecks()).toBe(1)
    })

    it('keeps a newer verified answer when an older poll answers after it', async () => {
        await mountAndLoad()

        const releasePoll = backend.hold('email_status')
        await jest.advanceTimersByTimeAsync(10_000)
        const releaseRecheck = backend.hold('email_status')
        logic.actions.recheck()
        await jest.advanceTimersByTimeAsync(0)

        backend.verifyDomain(DOMAIN)
        releaseRecheck()
        await jest.advanceTimersByTimeAsync(0)
        backend.sesReports(DOMAIN, 'pending')
        releasePoll()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.status?.verified).toBe(true)
    })

    it('shows a check as running only while a check the person asked for is in flight', async () => {
        await mountAndLoad()

        const releasePoll = backend.hold('email_status')
        await jest.advanceTimersByTimeAsync(10_000)
        expect(logic.values.statusLoading).toBe(true)
        expect(logic.values.rechecking).toBe(false)
        releasePoll()
        await jest.advanceTimersByTimeAsync(0)

        const releaseRecheck = backend.hold('email_status')
        logic.actions.recheck()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.rechecking).toBe(true)
        releaseRecheck()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.rechecking).toBe(false)
    })

    it('rechecks right after verification restarts, and stays usable when the restart fails', async () => {
        backend.sesReports(DOMAIN, 'failed')
        await mountAndLoad()
        expect(logic.values.status?.status).toBe('failed')

        backend.failOnce('email_verify', { status: 500, body: { detail: 'SES is down' } })
        logic.actions.restartVerification()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.restartResultLoading).toBe(false)
        expect(logic.values.status?.status).toBe('failed')

        logic.actions.restartVerification()
        await jest.advanceTimersByTimeAsync(0)
        expect(backend.requestsTo('email_verify')).toHaveLength(2)
        expect(logic.values.status?.status).toBe('pending')
    })

    it('keeps checking after a restart when the first check finds the provider unavailable', async () => {
        backend.sesReports(DOMAIN, 'failed')
        await mountAndLoad()
        expect(logic.values.status?.status).toBe('failed')

        backend.failOnce('email_status', { status: 503, body: { code: 'email_provider_unavailable' } })
        logic.actions.restartVerification()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.status?.status).toBe('failed')

        await jest.advanceTimersByTimeAsync(10_000)
        expect(logic.values.status?.status).toBe('pending')
    })
})
