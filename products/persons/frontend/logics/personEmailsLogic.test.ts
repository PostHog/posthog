import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personEmailsLogic } from './personEmailsLogic'

const NOW = '2026-03-15T12:00:00.000Z'

const asset = (invocation_id: string, recipient: string, sent_at: string): Record<string, string> => ({
    invocation_id,
    action_id: 'action-1',
    function_id: 'flow-1',
    function_name: 'Password reset',
    parent_run_id: '',
    kind: 'email',
    distinct_id: 'user-1',
    person_id: 'person-1',
    recipient,
    subject: 'Reset your password',
    status: 'sent',
    sent_at,
})

const logEntry = (
    message_id: string,
    recipient: string,
    opened: boolean,
    clicked: boolean
): Record<string, unknown> => ({
    message_id,
    recipient,
    created_at: '2026-03-14T09:00:00Z',
    status: 'delivered',
    opened,
    clicked,
})

describe('personEmailsLogic', () => {
    let logic: ReturnType<typeof personEmailsLogic.build>
    let searches: string[]

    beforeEach(() => {
        jest.useFakeTimers({
            now: new Date(NOW),
            doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate', 'setTimeout', 'clearTimeout'],
        })
        searches = []
        useMocks({
            get: {
                '/api/projects/:team_id/persons/:id/emails/': () => [
                    200,
                    [
                        asset('msg-clicked', 'Ada@example.com', '2026-03-14T09:00:01Z'),
                        asset('msg-opened', 'ada@example.com', '2026-03-13T09:00:01Z'),
                        asset('msg-unopened', 'ada@work.example.com', '2026-03-12T09:00:01Z'),
                        asset('msg-workflow', 'ada@example.com', '2026-03-11T09:00:01Z'),
                        asset('msg-old', 'ada@old.example.com', '2026-01-01T09:00:01Z'),
                    ],
                ],
                '/api/projects/:team_id/transactional_email_log/': ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search') ?? ''
                    searches.push(search)
                    return [
                        200,
                        {
                            has_more: false,
                            results: [
                                logEntry('msg-clicked', 'ada@example.com', true, true),
                                logEntry('msg-opened', 'ada@example.com', true, false),
                                logEntry('msg-unopened', 'ada@work.example.com', false, false),
                                logEntry('msg-other-recipient', 'jada@example.com', true, true),
                            ].filter((entry) => (entry.recipient as string).includes(search)),
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    const open = async (timeline: boolean): Promise<void> => {
        featureFlagLogic.mount()
        const flags = [
            FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API,
            ...(timeline ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE] : []),
        ]
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        logic = personEmailsLogic({ teamId: 1, personId: 'person-1' })
        logic.mount()
        logic.actions.loadEmails()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('says what each transactional email led to, once per recipient kept in the log', async () => {
        await open(true)

        expect(searches.sort()).toEqual(['ada@example.com', 'ada@work.example.com'])
        expect(logic.values.emails.map((email) => logic.values.outcomes?.[email.invocation_id] ?? null)).toEqual([
            'clicked',
            'opened',
            'not_opened',
            null,
            null,
        ])
    })

    it('leaves the emails as they were with the timeline off', async () => {
        await open(false)

        expect(searches).toEqual([])
        expect(logic.values.outcomes).toBeNull()
    })
})
