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
const KEPT = '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5b'
const SECOND_KEPT = '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5c'
const EXPIRED = '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5d'
const BUSY = '0195f3a8-1c2d-7e4f-8a9b-0c1d2e3f4a5e'
const PERSON_PAGE = `/project/997${urls.personByUUID('person-1')}`

const asset = (overrides: Partial<MessageAsset>): MessageAsset =>
    ({
        invocation_id: KEPT,
        action_id: 'transactional_email',
        function_id: 'flow-1',
        subject: 'Your receipt',
        recipient: 'ada@example.com',
        sent_at: dayjs().subtract(1, 'day').toISOString(),
        ...overrides,
    }) as MessageAsset

const sendPage = (id: string): string => `/project/997${urls.transactionalEmailLogEntry(id)}`

describe('personEmailsLogic', () => {
    let lookups: string[]
    let held: Record<string, Promise<void>>

    const mountWith = (flags: string[]): ReturnType<typeof personEmailsLogic.build> => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        const logic = personEmailsLogic({ teamId: 997, personId: 'person-1' })
        logic.mount()
        return logic
    }

    const hold = (id: string): (() => void) => {
        let release = (): void => {}
        held[id] = new Promise((resolve) => {
            release = resolve
        })
        return release
    }

    beforeEach(() => {
        lookups = []
        held = {}
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/:id/': async ({ params }) => {
                    const id = params.id as string
                    lookups.push(id)
                    await held[id]
                    if (id === EXPIRED) {
                        return [404, { detail: 'Not found.' }]
                    }
                    if (id === BUSY) {
                        return [429, { detail: 'Too many queries.' }]
                    }
                    return [200, { message_id: id }]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.personByUUID('person-1'))
    })

    test.each([
        ['a send the log keeps opens its send page', SEND_FLAGS, asset({}), sendPage(KEPT), [KEPT]],
        [
            'a send the log no longer has opens its preview',
            SEND_FLAGS,
            asset({ invocation_id: EXPIRED }),
            null,
            [EXPIRED],
        ],
        [
            'a busy log still opens the send page, which offers a retry',
            SEND_FLAGS,
            asset({ invocation_id: BUSY }),
            sendPage(BUSY),
            [BUSY],
        ],
        [
            'a send older than the log opens its preview without asking the log',
            SEND_FLAGS,
            asset({ sent_at: dayjs().subtract(31, 'day').toISOString() }),
            null,
            [],
        ],
        ['a workflow email opens its preview', SEND_FLAGS, asset({ action_id: 'action_email_1' }), null, []],
        ['without the flags a send opens its preview', [], asset({}), null, []],
    ])('%s', async (_name, flags, email, expectedPage, expectedLookups) => {
        const logic = mountWith(flags)

        await expectLogic(logic, () => logic.actions.openEmail(email)).toFinishAllListeners()

        expect(lookups).toEqual(expectedLookups)
        expect(logic.values.openingEmail).toBe(false)
        expect(logic.values.previewedEmail).toEqual(expectedPage ? null : email)
        expect(router.values.location.pathname).toBe(expectedPage ?? PERSON_PAGE)
    })

    it('opens the send clicked last when an earlier lookup answers late', async () => {
        const logic = mountWith(SEND_FLAGS)
        const releaseFirst = hold(KEPT)

        logic.actions.openEmail(asset({}))
        await expectLogic(logic, () =>
            logic.actions.openEmail(asset({ invocation_id: SECOND_KEPT }))
        ).toDispatchActions(['openSendPage'])
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(sendPage(SECOND_KEPT))
    })

    it('opens nothing when the tab closed before the lookup answered', async () => {
        const logic = mountWith(SEND_FLAGS)
        const release = hold(EXPIRED)

        logic.actions.openEmail(asset({ invocation_id: EXPIRED }))
        logic.unmount()
        release()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.previewedEmail).toBeNull()
        expect(router.values.location.pathname).toBe(PERSON_PAGE)
    })
})
