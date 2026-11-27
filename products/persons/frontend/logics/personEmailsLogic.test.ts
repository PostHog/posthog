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

const asset = (overrides: Partial<MessageAsset>): MessageAsset =>
    ({
        invocation_id: 'msg-1',
        action_id: 'transactional_email',
        function_id: 'flow-1',
        sent_at: dayjs().subtract(1, 'day').toISOString(),
        ...overrides,
    }) as MessageAsset

describe('personEmailsLogic', () => {
    let logged: Set<string>
    let lookups: string[]

    beforeEach(() => {
        logged = new Set(['msg-1'])
        lookups = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/:id/': ({ params }) => {
                    lookups.push(params.id as string)
                    return logged.has(params.id as string) ? [200, { message_id: params.id }] : [404, {}]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.personByUUID('person-1'))
    })

    test.each([
        ['a send the log keeps opens its send page', SEND_FLAGS, asset({}), true, ['msg-1']],
        [
            'a send the log no longer has keeps the preview',
            SEND_FLAGS,
            asset({ invocation_id: 'msg-expired' }),
            false,
            ['msg-expired'],
        ],
        [
            'a send older than the log keeps the preview without asking the log',
            SEND_FLAGS,
            asset({ sent_at: dayjs().subtract(31, 'day').toISOString() }),
            false,
            [],
        ],
        ['a workflow email keeps the preview', SEND_FLAGS, asset({ action_id: 'action_email_1' }), false, []],
        ['without the flags a send keeps the preview', [], asset({}), false, []],
    ])('%s', async (_name, flags, email, opensSendPage, expectedLookups) => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        const logic = personEmailsLogic({ teamId: 997, personId: 'person-1' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.openEmail(email)).toFinishAllListeners()

        expect(lookups).toEqual(expectedLookups)
        expect(logic.values.openingEmail).toBe(false)
        expect(logic.values.previewedEmail).toEqual(opensSendPage ? null : email)
        expect(router.values.location.pathname).toBe(
            `/project/997${opensSendPage ? urls.transactionalEmailLogEntry(email.invocation_id) : urls.personByUUID('person-1')}`
        )
    })
})
