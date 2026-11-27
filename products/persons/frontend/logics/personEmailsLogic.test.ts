import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personEmailsLogic } from './personEmailsLogic'

const NOW = '2026-03-15T12:00:00.000Z'

const CLICKED = '0190a000-0000-7000-8000-000000000001'
const OPENED = '0190a000-0000-7000-8000-000000000002'
const NO_OPEN = '0190a000-0000-7000-8000-000000000003'
const BOUNCED = '0190a000-0000-7000-8000-000000000004'
const NOT_SENT = '0190a000-0000-7000-8000-000000000007'
const WORKFLOW = '0190a000-0000-7000-8000-000000000005'
const OLD = '0190a000-0000-7000-8000-000000000006'
const FLAGS = [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API, FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE]

const asset = (invocation_id: string, sent_at: string, action_id = 'action-1'): Record<string, string> => ({
    invocation_id,
    action_id,
    function_id: 'flow-1',
    function_name: 'Password reset',
    parent_run_id: '',
    kind: 'email',
    distinct_id: 'user-1',
    person_id: 'person-1',
    recipient: 'ada@example.com',
    subject: 'Reset your password',
    status: 'sent',
    sent_at,
})

const logEntry = (
    message_id: string,
    recipient: string,
    status: string,
    opened: boolean,
    clicked: boolean,
    created_at = '2026-03-14T09:00:00Z'
): Record<string, unknown> => ({
    message_id,
    recipient,
    created_at,
    status,
    opened,
    clicked,
})

const LOG = [
    ...Array.from({ length: 150 }, (_, index) =>
        logEntry(
            `0190b000-0000-7000-8000-${String(index).padStart(12, '0')}`,
            'jada@example.com',
            'delivered',
            true,
            true
        )
    ),
    logEntry(CLICKED, 'ada@example.com', 'delivered', true, true),
    logEntry(OPENED, 'ada@example.com', 'delivered', true, false),
    logEntry(NO_OPEN, 'ada@example.com', 'delivered', false, false),
    logEntry(BOUNCED, 'ada@example.com', 'bounced', false, false),
    logEntry(NOT_SENT, 'ada@example.com', 'failed', false, false),
    logEntry(OLD, 'ada@example.com', 'delivered', true, true, '2026-02-10T09:00:00Z'),
]

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

describe('personEmailsLogic', () => {
    let logic: ReturnType<typeof personEmailsLogic.build>
    let searches: string[]
    let failing: Set<string>
    let held: { ids: string[]; reached: () => void; answer: Promise<void> } | null

    beforeEach(() => {
        jest.useFakeTimers({
            now: new Date(NOW),
            doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate', 'setTimeout', 'clearTimeout'],
        })
        searches = []
        failing = new Set()
        held = null
        useMocks({
            get: {
                '/api/projects/:team_id/persons/:id/emails/': () => [
                    200,
                    [
                        asset(CLICKED, '2026-03-14T09:00:02Z', 'action-2'),
                        asset(CLICKED, '2026-03-14T09:00:01Z'),
                        asset(OPENED, '2026-03-13T09:00:01Z'),
                        asset(NO_OPEN, '2026-03-12T09:00:01Z'),
                        asset(BOUNCED, '2026-03-11T09:00:01Z'),
                        asset(NOT_SENT, '2026-03-10T10:00:01Z'),
                        asset(WORKFLOW, '2026-03-10T09:00:01Z'),
                        asset(OLD, '2026-02-20T09:00:01Z'),
                    ],
                ],
                '/api/projects/:team_id/transactional_email_log/': async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const search = params.get('search') ?? ''
                    const limit = Number(params.get('limit') ?? 50)
                    const from = params.get('date_from') ?? '2026-03-08T12:00:00.000Z'
                    searches.push(search)
                    if (held?.ids.includes(search)) {
                        held.reached()
                        await held.answer
                    }
                    if (failing.has(search)) {
                        return [500, { detail: 'Server error' }]
                    }
                    const matches = LOG.filter(
                        (entry) =>
                            (entry.created_at as string) >= from &&
                            (UUID.test(search)
                                ? entry.message_id === search
                                : (entry.recipient as string).includes(search.toLowerCase()))
                    )
                    return [200, { results: matches.slice(0, limit), has_more: matches.length > limit }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    const setFlags = (on: boolean): void => {
        const flags = on ? FLAGS : [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    const open = async (on: boolean): Promise<void> => {
        setFlags(on)
        logic = personEmailsLogic({ teamId: 1, personId: 'person-1' })
        logic.mount()
        logic.actions.loadEmails()
        await expectLogic(logic).toFinishAllListeners()
    }

    const hold = (...ids: string[]): { reached: Promise<void>; release: () => void } => {
        let release = (): void => {}
        const reached = new Promise<void>((resolve) => {
            held = {
                ids,
                reached: resolve,
                answer: new Promise<void>((answer) => (release = answer)),
            }
        })
        return { reached, release: () => release() }
    }

    const lookupsInOrder = (): (string | null)[] =>
        logic.values.emails.map((email) => logic.values.lookups?.[email.invocation_id] ?? null)

    it('says what each recent email led to, looking each one up by its message ID', async () => {
        await open(true)

        expect(searches.sort()).toEqual([CLICKED, OPENED, NO_OPEN, BOUNCED, NOT_SENT, WORKFLOW, OLD].sort())
        expect(lookupsInOrder()).toEqual([
            'clicked',
            'clicked',
            'opened',
            'delivered',
            'bounced',
            'failed',
            'not_logged',
            'not_logged',
        ])
        expect(logic.values.outcomeColumnShown).toBe(true)
    })

    it('keeps the other outcomes when one lookup fails', async () => {
        failing.add(OPENED)

        await open(true)

        expect(lookupsInOrder()).toEqual([
            'clicked',
            'clicked',
            'unavailable',
            'delivered',
            'bounced',
            'failed',
            'not_logged',
            'not_logged',
        ])
    })

    it('opens the send page for a logged email and the preview for any other', async () => {
        await open(true)
        const [clicked, , , , , notSent, workflow] = logic.values.emails

        logic.actions.openEmail(workflow)
        expect(logic.values.previewed).toEqual(workflow)

        logic.actions.closePreview()
        logic.actions.openEmail(clicked)
        expect(router.values.location.pathname).toContain(urls.transactionalEmailLogEntry(CLICKED))

        logic.actions.openEmail(notSent)
        expect(router.values.location.pathname).toContain(urls.transactionalEmailLogEntry(NOT_SENT))
        expect(logic.values.previewed).toBeNull()
    })

    it('opens an email clicked while its lookup runs once the lookup answers', async () => {
        const lookup = hold(CLICKED)
        setFlags(true)
        logic = personEmailsLogic({ teamId: 1, personId: 'person-1' })
        logic.mount()
        logic.actions.loadEmails()
        await lookup.reached
        expect(logic.values.lookups?.[CLICKED]).toBe('looking')

        logic.actions.openEmail(logic.values.emails[0])
        expect(logic.values.previewed).toBeNull()
        expect(router.values.location.pathname).not.toContain(CLICKED)

        lookup.release()
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain(urls.transactionalEmailLogEntry(CLICKED))
    })

    it('follows the flags after the emails load', async () => {
        await open(false)
        expect(searches).toEqual([])
        expect(logic.values.outcomeColumnShown).toBe(false)

        setFlags(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.outcomeColumnShown).toBe(true)

        setFlags(false)
        logic.actions.openEmail(logic.values.emails[0])
        expect(logic.values.outcomeColumnShown).toBe(false)
        expect(logic.values.previewed).toEqual(logic.values.emails[0])
    })

    it('stops looking up once a flag turns off', async () => {
        const lookups = hold(CLICKED, OPENED, NO_OPEN, BOUNCED, NOT_SENT, WORKFLOW, OLD)
        setFlags(true)
        logic = personEmailsLogic({ teamId: 1, personId: 'person-1' })
        logic.mount()
        logic.actions.loadEmails()
        await lookups.reached

        setFlags(false)
        lookups.release()
        await expectLogic(logic).toFinishAllListeners()

        expect(searches.length).toBeLessThan(new Set(logic.values.emails.map((email) => email.invocation_id)).size)
        expect(logic.values.outcomeColumnShown).toBe(false)
    })
})
