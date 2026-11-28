import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MessageAsset } from 'products/workflows/frontend/Workflows/messageAssetsApi'

import { personEmailsLogic } from './personEmailsLogic'

const SEND_FLAGS = [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_TIMELINE, FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]
const SEND = '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5b'
const PERSON_PAGE = `/project/997${urls.personByUUID('person-1')}`
const SEND_PAGE = `/project/997${urls.transactionalEmailLogEntry(SEND)}`

const asset = (overrides: Partial<MessageAsset>): MessageAsset =>
    ({
        invocation_id: SEND,
        action_id: 'transactional_email',
        function_id: 'flow-1',
        subject: 'Your receipt',
        recipient: 'ada@example.com',
        sent_at: dayjs().subtract(1, 'day').toISOString(),
        in_transactional_email_log: true,
        ...overrides,
    }) as MessageAsset

describe('personEmailsLogic', () => {
    let requests: string[]

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/:id/': ({ params }) => {
                    requests.push(params.id as string)
                    return [200, { message_id: params.id }]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.personByUUID('person-1'))
    })

    test.each([
        ['a send the log keeps opens its send page', SEND_FLAGS, asset({}), SEND_PAGE],
        [
            'a send the log no longer has opens its preview',
            SEND_FLAGS,
            asset({ in_transactional_email_log: false }),
            null,
        ],
        [
            'a send the log could not be checked for opens its send page, which offers a retry',
            SEND_FLAGS,
            asset({ in_transactional_email_log: null }),
            SEND_PAGE,
        ],
        [
            'a send older than the log opens its preview',
            SEND_FLAGS,
            asset({ sent_at: dayjs().subtract(31, 'day').toISOString() }),
            null,
        ],
        [
            'a workflow email opens its preview',
            SEND_FLAGS,
            asset({ action_id: 'action_email_1', in_transactional_email_log: undefined }),
            null,
        ],
        ['without the flags a send opens its preview', [], asset({}), null],
    ])('%s', async (_name, flags, email, expectedPage) => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        const logic = personEmailsLogic({ teamId: 997, personId: 'person-1' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.openEmail(email)).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(expectedPage ?? PERSON_PAGE)
        expect(logic.values.previewedEmail).toEqual(expectedPage ? null : email)
        expect(requests).toEqual([])
    })
})
