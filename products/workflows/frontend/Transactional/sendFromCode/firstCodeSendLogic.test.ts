import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailsLogic } from '../transactionalEmailsLogic'
import { SendFromCodeSurface, firstCodeSendLogic } from './firstCodeSendLogic'

const TEAM_ID = 42

const codeEmail = (key: string, createdAt = '2026-11-15T10:00:00Z'): CodeEmailApi => ({
    id: `id-${key}`,
    key,
    hog_flow_id: `flow-${key}`,
    description: '',
    tags: [],
    sensitive: true,
    source_url: null,
    source_origin: null,
    created_at: createdAt,
    user_access_level: 'editor',
})

describe('firstCodeSendLogic', () => {
    let logic: ReturnType<typeof firstCodeSendLogic.build>
    let stored: CodeEmailApi[]
    let listFails: boolean

    beforeEach(() => {
        jest.useFakeTimers()
        stored = []
        listFails = false
        useMocks({
            get: {
                [`/api/projects/${TEAM_ID}/transactional_code_emails/`]: () =>
                    listFails ? [500, { detail: 'A server error occurred.' }] : [200, stored],
                [`/api/projects/${TEAM_ID}/messaging_templates/`]: { results: [] },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: TEAM_ID })
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    const mount = async (surface: SendFromCodeSurface = 'email_domain'): Promise<void> => {
        logic = firstCodeSendLogic({ surface })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
    }

    it('reports the first email once a later check finds it', async () => {
        await mount()
        expect(logic.values.firstCodeSend).toEqual({ status: 'waiting' })

        stored = [codeEmail('welcome')]
        await jest.advanceTimersByTimeAsync(10_000)

        expect(logic.values.firstCodeSend).toEqual({ status: 'arrived', codeEmail: codeEmail('welcome') })
    })

    it('counts a send as first when the tab already found no emails, even if its own first check fails', async () => {
        const tab = transactionalEmailsLogic()
        tab.mount()
        await jest.advanceTimersByTimeAsync(0)
        listFails = true
        await mount('transactional')

        stored = [codeEmail('welcome')]
        listFails = false
        await jest.advanceTimersByTimeAsync(10_000)

        expect(logic.values.firstCodeSend).toEqual({ status: 'arrived', codeEmail: codeEmail('welcome') })
        tab.unmount()
    })

    it.each([
        ['the first email when it is newer than the page', '2026-11-15T10:00:01Z', 'arrived'],
        ['no first email when it is older than the page', '2026-11-15T09:59:59Z', 'already_sending'],
    ])('after a failed first check, reports %s', async (_case, createdAt, status) => {
        jest.setSystemTime(new Date('2026-11-15T10:00:00Z'))
        listFails = true
        await mount()

        stored = [codeEmail('welcome', createdAt)]
        listFails = false
        await jest.advanceTimersByTimeAsync(10_000)

        expect(logic.values.firstCodeSend.status).toEqual(status)
    })

    it('does not call an email first when the project already sent from code', async () => {
        stored = [codeEmail('password-reset')]
        await mount()
        stored = [codeEmail('password-reset'), codeEmail('welcome')]
        await jest.advanceTimersByTimeAsync(60_000)

        expect(logic.values.firstCodeSend).toEqual({ status: 'already_sending' })
    })

    it('says its checks failed once polling stops, and checks again on request', async () => {
        listFails = true
        await mount()
        await jest.advanceTimersByTimeAsync(31 * 60_000)

        expect(logic.values).toMatchObject({ pollingStopped: true, lastCheckFailed: true })

        listFails = false
        logic.actions.checkAgain()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.firstCodeSend).toEqual({ status: 'waiting' })
        expect(logic.values).toMatchObject({ pollingStopped: false, lastCheckFailed: false })
    })
})
