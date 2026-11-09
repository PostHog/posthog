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
})

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
                '/api/projects/:team_id/transactional_code_emails/:id/': async ({ request, params }) => {
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
                '/api/projects/:team_id/transactional_code_emails/': [codeEmail('k', 'password-changed', ['auth'])],
                '/api/projects/:team_id/tags': ['auth', 'billing'],
            },
        })
        initKeaTests()
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
})
