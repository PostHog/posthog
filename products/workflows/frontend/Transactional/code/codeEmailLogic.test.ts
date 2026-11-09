import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi, PatchedCodeEmailUpdateApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'

// The code email endpoints are scoped by team, so the mocks answer only under the team's id.
const TEAM_ID = 42
const PROJECT_ID = 7
const EMAIL_URL = `/api/projects/${TEAM_ID}/transactional_code_emails/:id/`

const stored = (fields: Partial<CodeEmailApi> = {}): CodeEmailApi => ({
    id: 'email-id',
    key: 'password-reset',
    hog_flow_id: 'flow-id',
    description: '',
    tags: [],
    sensitive: true,
    source_url: null,
    created_at: '2026-01-01T00:00:00Z',
    user_access_level: 'editor',
    ...fields,
})

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve: () => void = () => {}
    const promise = new Promise<void>((r) => (resolve = r))
    return { promise, resolve }
}

describe('codeEmailLogic', () => {
    let logic: ReturnType<typeof codeEmailLogic.build>

    beforeEach(() => {
        initKeaTests(
            true,
            { ...MOCK_DEFAULT_TEAM, id: TEAM_ID, project_id: PROJECT_ID },
            { ...MOCK_DEFAULT_PROJECT, id: PROJECT_ID }
        )
    })

    afterEach(() => logic?.unmount())

    it.each([
        [404, 'not-found'],
        [500, 'failed'],
    ])('shows loading until the email answers, then %s as %s', async (status, loadState) => {
        const answer = deferred()
        useMocks({
            get: {
                [EMAIL_URL]: async () => {
                    await answer.promise
                    return [status, { detail: 'Nope' }]
                },
            },
        })
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()

        expect(logic.values.loadState).toEqual('loading')
        answer.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadState).toEqual(loadState)
        expect(logic.values.codeEmail).toBeNull()
    })

    it('loads the email after a failed load is retried', async () => {
        let calls = 0
        useMocks({ get: { [EMAIL_URL]: () => (++calls === 1 ? [500, {}] : [200, stored()]) } })
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadCodeEmail()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadState).toEqual('loaded')
        expect(logic.values.codeEmail?.key).toEqual('password-reset')
    })

    it.each([
        ['viewer', false],
        ['editor', true],
    ])('lets a reader with %s access to the email edit it: %s', async (level, canEdit) => {
        useMocks({ get: { [EMAIL_URL]: stored({ user_access_level: level }) } })
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editDisabledReason === null).toBe(canEdit)
    })

    it('saves one edit at a time and sends the edits made meanwhile together', async () => {
        const server = stored()
        const writes: PatchedCodeEmailUpdateApi[] = []
        const firstStarted = deferred()
        const releaseFirst = deferred()
        useMocks({
            get: { [EMAIL_URL]: () => [200, server] },
            patch: {
                [EMAIL_URL]: async ({ request }) => {
                    const fields = (await request.json()) as PatchedCodeEmailUpdateApi
                    writes.push(fields)
                    if (writes.length === 1) {
                        firstStarted.resolve()
                        await releaseFirst.promise
                    }
                    Object.assign(server, fields)
                    return [200, { ...server }]
                },
            },
        })
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.updateCodeEmail({ description: 'First' })
        await firstStarted.promise
        logic.actions.updateCodeEmail({ tags: ['auth'] })
        logic.actions.updateCodeEmail({ description: 'Second' })
        expect(writes).toHaveLength(1)
        releaseFirst.resolve()
        await expectLogic(logic).toDispatchActions(['updateCodeEmailSuccess'])
        expect(logic.values.codeEmail).toMatchObject({ description: 'Second', tags: ['auth'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([{ description: 'First' }, { tags: ['auth'], description: 'Second' }])
        expect(logic.values.codeEmail).toMatchObject({ description: 'Second', tags: ['auth'] })
        expect(logic.values.saving).toBe(false)
    })

    it('shows the stored values after a failed save and still sends the edit queued behind it', async () => {
        const writes: PatchedCodeEmailUpdateApi[] = []
        const releaseFirst = deferred()
        let gets = 0
        useMocks({
            get: { [EMAIL_URL]: () => (++gets === 1 ? [200, stored()] : [500, {}]) },
            patch: {
                [EMAIL_URL]: async ({ request }) => {
                    const fields = (await request.json()) as PatchedCodeEmailUpdateApi
                    writes.push(fields)
                    if (writes.length === 1) {
                        await releaseFirst.promise
                        return [400, { detail: 'Too long' }]
                    }
                    return [200, stored(fields)]
                },
            },
        })
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.updateCodeEmail({ description: 'Broken' })
        logic.actions.updateCodeEmail({ tags: ['auth'] })
        releaseFirst.resolve()
        await expectLogic(logic).toDispatchActions(['updateCodeEmailFailure'])
        expect(logic.values.codeEmail).toMatchObject({ description: '', tags: ['auth'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([{ description: 'Broken' }, { tags: ['auth'] }])
        expect(logic.values.codeEmail).toMatchObject({ description: '', tags: ['auth'] })
        expect(logic.values.saving).toBe(false)
    })

    it('reads the email back after a failed save without replacing an edit made meanwhile', async () => {
        const writes: PatchedCodeEmailUpdateApi[] = []
        const readBackStarted = deferred()
        const releaseReadBack = deferred()
        let gets = 0
        useMocks({
            get: {
                [EMAIL_URL]: async () => {
                    if (++gets > 1) {
                        readBackStarted.resolve()
                        await releaseReadBack.promise
                    }
                    return [200, stored()]
                },
            },
            patch: {
                [EMAIL_URL]: async ({ request }) => {
                    const fields = (await request.json()) as PatchedCodeEmailUpdateApi
                    writes.push(fields)
                    return writes.length === 1 ? [500, {}] : [200, stored(fields)]
                },
            },
        })
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.updateCodeEmail({ description: 'Broken' })
        await readBackStarted.promise
        logic.actions.updateCodeEmail({ tags: ['auth'] })
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(writes).toHaveLength(1)
        releaseReadBack.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([{ description: 'Broken' }, { tags: ['auth'] }])
        expect(logic.values.codeEmail).toMatchObject({ description: '', tags: ['auth'] })
    })
})
