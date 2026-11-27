import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

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
]

const steps = (
    ...kinds: TransactionalEmailLogDetailApi['timeline'][number]['kind'][]
): TransactionalEmailLogDetailApi['timeline'] => kinds.map((kind) => ({ kind, at: SENT, reason: null }))

const PERSON_ROWS = [['person-1', '{"email":"ada@example.com"}', '2025-01-01T00:00:00Z']]
const CLICK = {
    at: SENT,
    link_url: 'https://example.com/a',
    event_uuid: 'click-1',
    session: null,
    no_session_reason: 'not_found',
}
const UNLINKED_CLICK = { ...CLICK, link_url: null, event_uuid: null, no_session_reason: 'link_unknown' }
const ACTIVITY = {
    before: [{ uuid: 'ev-1' }],
    after: [],
    has_more_before: true,
    has_more_after: false,
    clicks: [CLICK],
    email_events: [],
}

const PANELS = ['person', 'activity', 'otherEmails'] as const
type Endpoint = 'detail' | (typeof PANELS)[number]

describe('transactionalEmailLogEntryLogic', () => {
    let logic: ReturnType<typeof transactionalEmailLogEntryLogic.build>
    let sends: Record<string, TransactionalEmailLogDetailApi>
    let failing: Set<Endpoint>
    let served: Endpoint[]
    let othersQuery: Record<string, string> | null
    let activity: [number, unknown]

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
        activity = [200, ACTIVITY]
        useMocks({
            get: {
                [`${LOG}:id/`]: ({ params }) =>
                    serve('detail', () => (sends[params.id as string] ? [200, sends[params.id as string]] : [404, {}])),
                [`${LOG}:id/activity/`]: ({ params }) =>
                    serve('activity', () => (sends[params.id as string] ? activity : [404, {}])),
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

    it('loads a send by its id, then its recipient, their activity, and their other emails', async () => {
        await open('msg-1')
        expect(logic.values.email).toEqual(SEND)
        expect(logic.values.person).toMatchObject({ id: 'person-1', properties: { email: 'ada@example.com' } })
        expect(logic.values.activity).toMatchObject({ before: [{ uuid: 'ev-1' }], after: [], hasMoreBefore: true })
        expect(othersQuery).toMatchObject({ search: 'Ada@example.com', date_from: WEEK_BEFORE_SENT, date_to: NOW })
        expect(logic.values.otherEmails.map((e) => e.message_id)).toEqual(['msg-2'])
    })

    it('keys its breadcrumb by the send id', async () => {
        await open('msg-1')
        expect(logic.values.breadcrumbs[2].key).toEqual(['TransactionalEmailLogEntry', 'msg-1'])
    })

    it('expands the activity before and after the send on their own', async () => {
        await open('msg-1')
        logic.actions.showAllBefore()
        expect(logic.values).toMatchObject({ beforeExpanded: true, afterExpanded: false })
        logic.actions.showAllAfter()
        expect(logic.values.afterExpanded).toBe(true)
    })

    const timelineFlag = (on: boolean): void => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(on ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE] : [], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE]: on,
        })
    }

    const sendWithoutPerson = (clicked: boolean): void => {
        sends['msg-9'] = {
            ...SEND,
            message_id: 'msg-9',
            distinct_id: '',
            recipient: '',
            clicked,
            timeline: clicked ? steps('sent', 'clicked') : steps('sent'),
        } as TransactionalEmailLogDetailApi
        activity = [200, { ...ACTIVITY, before: [], has_more_before: false, clicks: clicked ? [UNLINKED_CLICK] : [] }]
    }

    it.each([
        ['an unclicked send', false, true, ['detail'], []],
        ['a clicked send without the timeline', true, false, ['detail'], null],
        ['a clicked send with the timeline', true, true, ['detail', 'activity'], ['click']],
    ])(
        'loads for %s with no distinct id or recipient only what its clicks need',
        async (_name, clicked, timeline, endpoints, shownKinds) => {
            timelineFlag(timeline)
            sendWithoutPerson(clicked)
            await open('msg-9')
            expect(served).toEqual(endpoints)
            expect(logic.values.outcomesShown ? logic.values.outcomeRows?.map((row) => row.kind) : null).toEqual(
                shownKinds
            )
        }
    )

    it('loads the clicks of a send with no distinct id once the timeline turns on', async () => {
        timelineFlag(false)
        sendWithoutPerson(true)
        await open('msg-9')
        timelineFlag(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(served).toEqual(['detail', 'activity'])
        expect(logic.values).toMatchObject({ outcomesShown: true, outcomeRows: [{ kind: 'click', link: null }] })
    })

    it.each([
        ['went out without a stored copy', { action_id: '', timeline: steps('queued', 'sent', 'clicked') }, true],
        ['was delivered with no sent step recorded', { timeline: steps('delivered') }, true],
        ['failed before it went out', { timeline: steps('queued', 'failed') }, false],
    ])('shows what a send led to when it %s', async (_name, send, shown) => {
        timelineFlag(true)
        sends['msg-1'] = { ...SEND, ...send } as TransactionalEmailLogDetailApi
        await open('msg-1')
        expect(logic.values.outcomesShown).toBe(shown)
    })

    it.each([
        ['a click that came after the send loaded', false, ACTIVITY, ['click']],
        ['an activity response that predates clicks', true, { before: [], after: [] }, []],
    ])('lists what the activity found for %s', async (_name, clicked, response, outcomeKinds) => {
        sends['msg-1'] = { ...SEND, clicked, timeline: steps('sent') } as TransactionalEmailLogDetailApi
        activity = [200, response]
        await open('msg-1')
        expect(logic.values.outcomeRows?.map((row) => row.kind)).toEqual(outcomeKinds)
    })

    it.each([
        [403, true],
        [500, false],
    ])('marks an activity answered with %s as denied: %s', async (status, denied) => {
        activity = [status, { detail: 'no' }]
        await open('msg-1')
        expect(logic.values).toMatchObject({ activityFailed: true, activityDenied: denied })
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

    it.each([
        ['without the flag', undefined, { code_email_id: 'code-1', template_id: null }, null],
        ['with the flag off', false, { code_email_id: 'code-1', template_id: null }, null],
        [
            'with the flag off',
            false,
            { code_email_id: null, template_id: 'tpl-1' },
            urls.transactionalTemplate('tpl-1'),
        ],
        [
            'with the flag on',
            true,
            { code_email_id: 'code-1', template_id: null },
            `${urls.transactionalCodeEmail('code-1')}?tab=sends&status=bounced`,
        ],
        [
            'with the flag on',
            true,
            { code_email_id: null, template_id: 'tpl-1' },
            `${urls.transactionalTemplate('tpl-1')}?tab=sends&status=bounced`,
        ],
        ['with the flag on', true, { code_email_id: null, template_id: null }, null],
    ])('links a send opened from bounced sends %s from %j to %s', async (_name, sendLinks, email, emailPageUrl) => {
        if (sendLinks !== undefined) {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags(sendLinks ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS] : [], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS]: sendLinks,
            })
        }
        sends['msg-1'] = { ...SEND, ...email }
        router.actions.push(urls.transactionalEmailLogEntry('msg-1'), { status: 'bounced' })
        await open('msg-1')
        expect(logic.values.emailPageUrl).toEqual(emailPageUrl)
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
