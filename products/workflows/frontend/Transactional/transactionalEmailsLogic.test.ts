import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import type { MessageTemplate } from '../TemplateLibrary/types'
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
    created_at: '2026-01-01T00:00:00Z',
    user_access_level: 'editor',
})

// The code email endpoints are scoped by team, so the mocks below answer only under the team's id.
const TEAM_ID = 42
const PROJECT_ID = 7
const CODE_EMAILS = `/api/projects/${TEAM_ID}/transactional_code_emails/`

describe('transactionalEmailsLogic', () => {
    let logic: ReturnType<typeof transactionalEmailsLogic.build>
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
                '/api/projects/:team_id/tags': ['auth', 'billing'],
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

    it('keeps the newer tags when an older tag save answers last', async () => {
        let releaseFirst: () => void = () => {}
        let firstStarted: () => void = () => {}
        const firstRequest = new Promise<void>((resolve) => (firstStarted = resolve))
        useMocks({
            patch: {
                [`${CODE_EMAILS}:id/`]: async ({ request, params }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    writes.push({ path: `transactional_code_emails/${String(params.id)}`, tags })
                    if (writes.length === 1) {
                        firstStarted()
                        await new Promise<void>((resolve) => (releaseFirst = resolve))
                    }
                    return [200, codeEmail(String(params.id), 'password-changed', tags)]
                },
            },
        })
        const tagsShown = (): string[] =>
            logic.values.transactionalEmails.find((r) => r.name === 'password-changed')!.tags

        logic.actions.saveTransactionalTags(
            logic.values.transactionalEmails.find((r) => r.name === 'password-changed')!,
            ['auth', 'security']
        )
        await firstRequest
        logic.actions.saveTransactionalTags(
            logic.values.transactionalEmails.find((r) => r.name === 'password-changed')!,
            ['auth', 'security', 'urgent']
        )
        await expectLogic(logic).toDispatchActions(['transactionalTagsSaved'])
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(writes.map((write) => write.tags)).toEqual([
            ['auth', 'security'],
            ['auth', 'security', 'urgent'],
        ])
        expect(tagsShown()).toEqual(['auth', 'security', 'urgent'])
    })
})
