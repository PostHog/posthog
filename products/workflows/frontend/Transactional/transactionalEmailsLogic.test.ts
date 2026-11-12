import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import type { MessageTemplate } from '../TemplateLibrary/types'
import type { TransactionalEmailRow } from './transactionalEmailRows'
import { transactionalEmailsLogic } from './transactionalEmailsLogic'

const template = (id: string, name: string, tags: string[], createdBy: number, transactional = true): MessageTemplate =>
    ({
        id,
        name,
        description: '',
        tags,
        created_by: { id: createdBy },
        transactional_hog_flow_id: transactional ? `flow-${id}` : null,
    }) as unknown as MessageTemplate

const codeEmail = (id: string, key: string, tags: string[]): CodeEmailApi => ({
    id,
    key,
    hog_flow_id: `flow-${id}`,
    description: '',
    tags,
    sensitive: true,
    source_url: null,
    source_origin: null,
    created_at: '2026-01-01T00:00:00Z',
    user_access_level: 'editor',
})

// The code email endpoints are scoped by team, so the mocks below answer only under the team's id.
const TEAM_ID = 42
const PROJECT_ID = 7
const CODE_EMAILS = `/api/projects/${TEAM_ID}/transactional_code_emails/`

describe('transactionalEmailsLogic', () => {
    let logic: ReturnType<typeof transactionalEmailsLogic.build>
    const codeRow = (): TransactionalEmailRow =>
        logic.values.transactionalEmails.find((r) => r.name === 'password-changed')!
    let writes: { path: string; tags: string[] }[]

    beforeEach(async () => {
        writes = []
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': async ({ request, params }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    const id = String(params.id)
                    writes.push({ path: `messaging_templates/${id}`, tags })
                    return [200, { ...template(id, 'Password reset', [], 1), tags }]
                },
                [`${CODE_EMAILS}:id/`]: async ({ request, params }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    const id = String(params.id)
                    writes.push({ path: `transactional_code_emails/${id}`, tags })
                    return [200, codeEmail(id, 'password-changed', tags)]
                },
            },
            get: {
                '/api/projects/:team_id/messaging_templates/': {
                    results: [
                        template('a', 'Password reset', ['auth'], 1),
                        template('b', 'Receipt', ['billing'], 2),
                        template('c', 'Sign-in code', ['auth'], 2),
                        template('d', 'Newsletter', ['auth'], 1, false),
                    ],
                },
                [CODE_EMAILS]: [codeEmail('k', 'password-changed', ['auth'])],
            },
        })
        initKeaTests(
            true,
            { ...MOCK_DEFAULT_TEAM, id: TEAM_ID, project_id: PROJECT_ID },
            { ...MOCK_DEFAULT_PROJECT, id: PROJECT_ID }
        )
        logic = transactionalEmailsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    it.each([
        [
            'a tag',
            `/transactional?tags=${encodeURIComponent('["auth"]')}`,
            ['Password reset', 'Sign-in code', 'password-changed'],
        ],
        ['the creator', '/transactional?created_by=2', ['Receipt', 'Sign-in code']],
        ['a search', '/transactional?search=password', ['Password reset', 'password-changed']],
        ['code', '/transactional?managed_by=code', ['password-changed']],
        ['PostHog', '/transactional?managed_by=posthog', ['Password reset', 'Receipt', 'Sign-in code']],
    ])('filters transactional emails by %s from the url', async (_name, url, expected) => {
        router.actions.push(url)

        await expectLogic(logic).toMatchValues({
            filteredTransactionalEmails: expected.map((name) => expect.objectContaining({ name })),
        })
    })

    it('writes the managed by filter into the url', () => {
        logic.actions.setFilters({ managedBy: 'code' })

        expect(router.values.searchParams).toMatchObject({ managed_by: 'code' })
    })

    it('keeps the filters when a link back to the list carries no query params', () => {
        router.actions.push('/transactional?search=reset&created_by=1')

        router.actions.push('/transactional')

        expect(logic.values.filters).toMatchObject({ search: 'reset', createdBy: 1 })
        expect(router.values.searchParams).toMatchObject({ search: 'reset' })
    })

    it.each([
        ['a template', 'Password reset', 'messaging_templates/a'],
        ['an email sent from code', 'password-changed', 'transactional_code_emails/k'],
    ])('saves two quick tag edits on %s as one write that keeps both tags', async (_source, name, path) => {
        const row = logic.values.transactionalEmails.find((r) => r.name === name)!

        logic.actions.saveTransactionalTags(row, ['auth', 'security'])
        const shown = logic.values.transactionalEmails.find((r) => r.name === name)!
        logic.actions.saveTransactionalTags(shown, [...shown.tags, 'urgent'])
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([{ path, tags: ['auth', 'security', 'urgent'] }])
        expect(logic.values.transactionalEmails.find((r) => r.name === name)!.tags).toEqual([
            'auth',
            'security',
            'urgent',
        ])
    })

    it('saves tag edits made on two rows within the same pause', async () => {
        const [reset, receipt] = ['Password reset', 'Receipt'].map(
            (name) => logic.values.transactionalEmails.find((r) => r.name === name)!
        )

        logic.actions.saveTransactionalTags(reset, ['auth', 'security'])
        logic.actions.saveTransactionalTags(receipt, ['billing', 'urgent'])
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([
            { path: 'messaging_templates/a', tags: ['auth', 'security'] },
            { path: 'messaging_templates/b', tags: ['billing', 'urgent'] },
        ])
    })

    it.each([404, 500])('keeps the template rows when the code emails answer %s', async (status) => {
        logic.unmount()
        useMocks({ get: { [CODE_EMAILS]: () => [status, { detail: 'Unavailable' }] } })
        logic = transactionalEmailsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.codeEmailsLoading).toBe(false)
        expect(logic.values.transactionalEmails.map((row) => row.name)).toEqual([
            'Password reset',
            'Receipt',
            'Sign-in code',
        ])
    })

    it.each([
        ['a template', 'answers', 'Password reset'],
        ['a template', 'fails', 'Password reset'],
        ['an email sent from code', 'answers', 'password-changed'],
        ['an email sent from code', 'fails', 'password-changed'],
    ])('stores every tag when edits on %s are made while the first save %s', async (_source, first, name) => {
        jest.useFakeTimers()
        try {
            let stored = ['auth']
            const held: (() => void)[] = []
            const save = async (request: Request, path: string): Promise<string[] | null> => {
                const { tags } = (await request.json()) as { tags: string[] }
                const write = writes.push({ path, tags })
                if (write <= 2) {
                    await new Promise<void>((resolve) => held.push(resolve))
                }
                if (write === 1 && first === 'fails') {
                    return null
                }
                stored = tags
                return tags
            }
            useMocks({
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': async ({ request, params }) => {
                        const tags = await save(request, `messaging_templates/${String(params.id)}`)
                        return tags
                            ? [200, { ...template(String(params.id), 'Password reset', [], 1), tags }]
                            : [500, { detail: 'Unavailable' }]
                    },
                    [`${CODE_EMAILS}:id/`]: async ({ request, params }) => {
                        const tags = await save(request, `transactional_code_emails/${String(params.id)}`)
                        return tags
                            ? [200, codeEmail(String(params.id), 'password-changed', tags)]
                            : [500, { detail: 'Unavailable' }]
                    },
                },
                get: {
                    '/api/projects/:team_id/messaging_templates/': () => [
                        200,
                        { results: [template('a', 'Password reset', stored, 1)] },
                    ],
                    [CODE_EMAILS]: () => [200, [codeEmail('k', 'password-changed', stored)]],
                },
            })
            const row = (): TransactionalEmailRow => logic.values.transactionalEmails.find((r) => r.name === name)!

            logic.actions.saveTransactionalTags(row(), ['auth', 'security'])
            await jest.advanceTimersByTimeAsync(300)
            logic.actions.saveTransactionalTags(row(), [...row().tags, 'urgent'])
            await jest.advanceTimersByTimeAsync(300)
            expect(writes).toHaveLength(1)
            held[0]()
            while (held.length < 2) {
                await jest.advanceTimersByTimeAsync(10)
            }
            await jest.advanceTimersByTimeAsync(100)
            logic.actions.saveTransactionalTags(row(), [...row().tags, 'later'])
            await jest.advanceTimersByTimeAsync(300)
            held[1]()
            await jest.advanceTimersByTimeAsync(0)
            await expectLogic(logic).toFinishAllListeners()

            const all = ['auth', 'security', 'urgent', 'later']
            expect(stored).toEqual(all)
            expect(row().tags).toEqual(all)
            logic.actions.loadCodeEmails()
            logic.actions.loadTemplates()
            await expectLogic(logic).toFinishAllListeners()
            expect(row().tags).toEqual(all)
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        [1, 200],
        [1, 500],
        [2, 500],
    ])(
        'shows the stored tags of an email sent from code when a burst of %s tag edits fails to save and the read-back answers %s',
        async (edits, status) => {
            useMocks({
                patch: { [`${CODE_EMAILS}:id/`]: () => [500, { detail: 'Unavailable' }] },
                get: { [`${CODE_EMAILS}:id/`]: () => [status, codeEmail('k', 'password-changed', ['auth'])] },
            })

            for (const tag of ['security', 'urgent'].slice(0, edits)) {
                logic.actions.saveTransactionalTags(codeRow(), [...codeRow().tags, tag])
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(codeRow().tags).toEqual(['auth'])
            expect(logic.values.savingTagsFor).toBeNull()
        }
    )

    it.each([200, 500])(
        'keeps a newer tag edit when the read-back of a failed save answers %s after it, also through a later failed edit',
        async (status) => {
            let outage = false
            let patches = 0
            let readBackStarted: () => void = () => {}
            const readBack = new Promise<void>((resolve) => (readBackStarted = resolve))
            let releaseReadBack: () => void = () => {}
            const readBackHeld = new Promise<void>((resolve) => (releaseReadBack = resolve))
            useMocks({
                patch: {
                    [`${CODE_EMAILS}:id/`]: async ({ request, params }) => {
                        const { tags } = (await request.json()) as { tags: string[] }
                        if (++patches === 1 || outage) {
                            return [500, { detail: 'Unavailable' }]
                        }
                        return [200, codeEmail(String(params.id), 'password-changed', tags)]
                    },
                },
                get: {
                    [`${CODE_EMAILS}:id/`]: async () => {
                        if (outage) {
                            return [500, { detail: 'Unavailable' }]
                        }
                        readBackStarted()
                        await readBackHeld
                        return [status, codeEmail('k', 'password-changed', ['auth'])]
                    },
                },
            })

            logic.actions.saveTransactionalTags(codeRow(), ['auth', 'security'])
            await readBack
            logic.actions.saveTransactionalTags(codeRow(), [...codeRow().tags, 'urgent'])
            await expectLogic(logic).toDispatchActions(['transactionalTagsSaved'])
            releaseReadBack()
            await expectLogic(logic).toFinishAllListeners()

            expect(codeRow().tags).toEqual(['auth', 'security', 'urgent'])
            outage = true
            logic.actions.saveTransactionalTags(codeRow(), [...codeRow().tags, 'later'])
            await expectLogic(logic).toFinishAllListeners()
            expect(codeRow().tags).toEqual(['auth', 'security', 'urgent'])
        }
    )
})
