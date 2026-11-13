import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEntryApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

const SENT = '2026-03-10T09:00:00.000Z'
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

const ACTIVITY = { before: [{ uuid: 'ev-1' }], after: [], has_more_before: true, has_more_after: false }

type Endpoint = 'detail' | 'person' | 'activity' | 'others'

describe('transactionalEmailLogEntryLogic', () => {
    let logic: ReturnType<typeof transactionalEmailLogEntryLogic.build>
    let sends: Record<string, TransactionalEmailLogDetailApi>
    let personRows: unknown[][]
    let failing: Set<Endpoint>
    let served: Endpoint[]
    let otherEmailsSearch: string | null

    const serve = (endpoint: Endpoint, answer: () => [number, any]): [number, any] => {
        served.push(endpoint)
        return failing.has(endpoint) ? [500, { detail: 'boom' }] : answer()
    }

    const open = async (messageId: string): Promise<void> => {
        logic = transactionalEmailLogEntryLogic({ messageId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        sends = { [SEND.message_id]: SEND }
        personRows = [['person-1', '{"email":"ada@example.com"}', '2025-01-01T00:00:00Z']]
        failing = new Set()
        served = []
        otherEmailsSearch = null
        useMocks({
            get: {
                [`${LOG}:id/`]: ({ params }) =>
                    serve('detail', () => (sends[params.id as string] ? [200, sends[params.id as string]] : [404, {}])),
                [`${LOG}:id/activity/`]: () => serve('activity', () => [200, ACTIVITY]),
                [LOG]: ({ request }) => {
                    otherEmailsSearch = new URL(request.url).searchParams.get('search')
                    return serve('others', () => [200, { has_more: false, results: OTHERS }])
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': () => serve('person', () => [200, { results: personRows }]),
            },
        })
        initKeaTests()
    })

    afterEach(() => logic.unmount())

    it('loads a send by its id, then its recipient, their activity, and their other emails', async () => {
        await open('msg-1')

        expect(logic.values.email).toEqual(SEND)
        expect(logic.values.person).toMatchObject({ id: 'person-1', properties: { email: 'ada@example.com' } })
        expect(logic.values.activity).toMatchObject({ before: [{ uuid: 'ev-1' }], after: [], hasMoreBefore: true })
        expect(otherEmailsSearch).toBe('Ada@example.com')
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

    it('marks each side panel failed on its own, and a retry clears it', async () => {
        failing = new Set(['person', 'activity', 'others'])
        await open('msg-1')
        expect(logic.values).toMatchObject({ personFailed: true, activityFailed: true, otherEmailsFailed: true })

        failing.clear()
        personRows = []
        logic.actions.loadPerson('user-1')
        logic.actions.loadActivity()
        logic.actions.loadOtherEmails(SEND)
        expect(logic.values).toMatchObject({ personFailed: false, activityFailed: false, otherEmailsFailed: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.person).toBeNull()
        expect(logic.values.activity?.hasMoreBefore).toBe(true)
        expect(logic.values.otherEmails).toHaveLength(1)
    })
})
