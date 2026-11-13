import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEntryApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

const SENT = '2026-03-10T09:00:00.000Z'
const NOW = '2026-03-15T12:00:00.000Z'
const WEEK_BEFORE_SENT = '2026-03-03T09:00:00.000Z'
const LOG = '/api/projects/:team_id/transactional_email_log/'

const SEND = {
    message_id: 'msg-1',
    created_at: SENT,
    status: 'delivered',
    recipient: 'Ada@example.com',
    distinct_id: 'user-1',
} as TransactionalEmailLogDetailApi

const OTHERS = [
    { message_id: 'msg-1', recipient: 'Ada@example.com', created_at: SENT },
    { message_id: 'msg-2', recipient: 'ada@example.com', created_at: '2026-03-12T00:00:00Z' },
] as TransactionalEmailLogEntryApi[]

const PERSON_ROWS = [['person-1', '{"email":"ada@example.com"}', '2025-01-01T00:00:00Z']]
const ACTIVITY = { before: [{ uuid: 'ev-1' }], after: [], has_more_before: true, has_more_after: false }

const PANELS = ['person', 'activity', 'otherEmails'] as const
type Endpoint = 'detail' | (typeof PANELS)[number]

describe('transactionalEmailLogEntryLogic', () => {
    let logic: ReturnType<typeof transactionalEmailLogEntryLogic.build>
    let sends: Record<string, TransactionalEmailLogDetailApi>
    let failing: Set<Endpoint>
    let served: Endpoint[]
    let othersQuery: Record<string, string> | null

    const serve = (endpoint: Endpoint, answer: () => [number, unknown]): [number, unknown] => {
        served.push(endpoint)
        return failing.has(endpoint) ? [500, { detail: 'boom' }] : answer()
    }

    const open = async (messageId: string): Promise<void> => {
        logic = transactionalEmailLogEntryLogic({ messageId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        jest.useFakeTimers({
            now: new Date(NOW),
            doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate', 'setTimeout', 'clearTimeout'],
        })
        sends = { [SEND.message_id]: SEND }
        failing = new Set()
        served = []
        othersQuery = null
        useMocks({
            get: {
                [`${LOG}:id/`]: ({ params }) =>
                    serve('detail', () => (sends[params.id as string] ? [200, sends[params.id as string]] : [404, {}])),
                [`${LOG}:id/activity/`]: ({ params }) =>
                    serve('activity', () => (sends[params.id as string] ? [200, ACTIVITY] : [404, {}])),
                [LOG]: ({ request }) => {
                    othersQuery = Object.fromEntries(new URL(request.url).searchParams)
                    return serve('otherEmails', () => [200, { has_more: false, results: OTHERS }])
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { query: string } }
                    const rows = query.query.includes("'user-1'") ? PERSON_ROWS : []
                    return serve('person', () => [200, { results: rows }])
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => logic.unmount())

    it('opens a send with its person, activity, other emails, breadcrumbs, and expand toggles', async () => {
        await open('msg-1')
        expect(logic.values.email).toEqual(SEND)
        expect(logic.values.person).toMatchObject({ id: 'person-1', properties: { email: 'ada@example.com' } })
        expect(logic.values.activity).toMatchObject({ before: [{ uuid: 'ev-1' }], after: [], hasMoreBefore: true })
        expect(othersQuery).toMatchObject({ search: 'Ada@example.com', date_from: WEEK_BEFORE_SENT, date_to: NOW })
        expect(logic.values.otherEmails.map((e) => e.message_id)).toEqual(['msg-2'])
        expect(logic.values.breadcrumbs.map((b) => b.name)).toEqual(['Transactional', 'Log', 'Email'])
        expect(logic.values.breadcrumbs[2].key).toEqual(['TransactionalEmailLogEntry', 'msg-1'])
        logic.actions.showAllBefore()
        expect(logic.values).toMatchObject({ beforeExpanded: true, afterExpanded: false })
        logic.actions.showAllAfter()
        expect(logic.values.afterExpanded).toBe(true)
    })

    it('loads nothing else for a send with no distinct id or recipient', async () => {
        sends['msg-9'] = { ...SEND, message_id: 'msg-9', distinct_id: '', recipient: '' }
        await open('msg-9')
        expect(logic.values.email?.message_id).toBe('msg-9')
        expect(served).toEqual(['detail'])
    })

    it('tells a send that does not exist apart from one that failed to load', async () => {
        await open('missing')
        expect(logic.values).toMatchObject({ email: null, emailFailed: false })
        logic.unmount()

        failing.add('detail')
        await open('msg-1')
        expect(logic.values.emailFailed).toBe(true)

        failing.delete('detail')
        logic.actions.loadEmail()
        expect(logic.values.emailFailed).toBe(false)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.email).toEqual(SEND)
    })

    it.each(PANELS)('marks only the %s panel failed, and a retry clears it', async (panel) => {
        failing.add(panel)
        await open('msg-1')
        const flags = (): boolean[] => PANELS.map((p) => logic.values[`${p}Failed` as const])
        expect(flags()).toEqual(PANELS.map((p) => p === panel))
        failing.clear()
        logic.actions.loadPerson('user-1')
        logic.actions.loadActivity()
        logic.actions.loadOtherEmails(SEND)
        expect(flags()).toEqual([false, false, false])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.person).toMatchObject({ id: 'person-1' })
        expect(logic.values.activity?.hasMoreBefore).toBe(true)
        expect(logic.values.otherEmails).toHaveLength(1)
    })
})
