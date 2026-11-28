import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { mswServer, useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PersonEmailApi } from 'products/persons/frontend/generated/api.schemas'

import { personEmailsLogic } from './personEmailsLogic'

const SEND_FLAGS = [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE, FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]
const SEND = '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5b'
const PERSON_PAGE = `/project/997${urls.personByUUID('person-1')}`
const SEND_PAGE = `/project/997${urls.transactionalEmailLogEntry(SEND)}`

const row = (overrides: Partial<PersonEmailApi>): Partial<PersonEmailApi> => ({
    invocation_id: SEND,
    action_id: 'transactional_email',
    function_id: 'flow-1',
    function_name: 'Receipts',
    parent_run_id: '',
    kind: 'email',
    distinct_id: 'ada',
    person_id: 'person-1',
    recipient: 'ada@example.com',
    subject: 'Your receipt',
    status: 'sent',
    sent_at: dayjs().subtract(1, 'day').toISOString(),
    in_transactional_email_log: true,
    ...overrides,
})

const { in_transactional_email_log: _field, ...rowOfAnOlderServer } = row({})

describe('personEmailsLogic', () => {
    let requestsOnOpen: string[]

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.personByUUID('person-1'))
    })

    afterEach(() => mswServer.events.removeAllListeners())

    test.each([
        ['a send the log keeps opens its send page', SEND_FLAGS, row({}), SEND_PAGE],
        [
            'a send the log no longer has opens its preview',
            SEND_FLAGS,
            row({ in_transactional_email_log: false }),
            null,
        ],
        [
            'a send the log could not be checked for opens its preview',
            SEND_FLAGS,
            row({ in_transactional_email_log: null }),
            null,
        ],
        ['a send from a server that does not say opens its preview', SEND_FLAGS, rowOfAnOlderServer, null],
        [
            'a workflow email opens its preview',
            SEND_FLAGS,
            row({ action_id: 'action_email_1', in_transactional_email_log: null }),
            null,
        ],
        ['without the flags a send opens its preview', [], row({}), null],
    ])('%s', async (_name, flags, email, expectedPage) => {
        useMocks({ get: { '/api/projects/:team_id/persons/:id/emails/': [email] } })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        const logic = personEmailsLogic({ teamId: 997, personId: 'person-1' })
        logic.mount()
        await expectLogic(logic, () => void logic.values.emails).toDispatchActions(['loadEmailsSuccess'])
        const [loaded] = logic.values.emails
        requestsOnOpen = []
        mswServer.events.on('request:start', ({ request }) => requestsOnOpen.push(request.url))

        await expectLogic(logic, () => logic.actions.openEmail(loaded)).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(expectedPage ?? PERSON_PAGE)
        expect(logic.values.previewedEmail).toEqual(expectedPage ? null : email)
        expect(requestsOnOpen).toEqual([])
    })
})
