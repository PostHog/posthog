import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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

describe('transactionalEmailsLogic', () => {
    let logic: ReturnType<typeof transactionalEmailsLogic.build>
    let writes: { id: string; tags: string[] }[]

    beforeEach(async () => {
        writes = []
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': async ({ request, params }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    const id = String(params.id)
                    writes.push({ id, tags })
                    return [200, { ...template(id, 'Password reset', [], 1), tags }]
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
        ['a tag', `/transactional?tags=${encodeURIComponent('["auth"]')}`, ['Password reset', 'Sign-in code']],
        ['the creator', '/transactional?created_by=2', ['Receipt', 'Sign-in code']],
        ['a search', '/transactional?search=receipt', ['Receipt']],
    ])('filters transactional emails by %s from the url', async (_name, url, expected) => {
        router.actions.push(url)

        await expectLogic(logic).toMatchValues({
            filteredTransactionalTemplates: expected.map((name) => expect.objectContaining({ name })),
        })
    })

    it('keeps the filters when a link back to the list carries no query params', () => {
        router.actions.push('/transactional?search=reset&created_by=1')

        router.actions.push('/transactional')

        expect(logic.values.filters).toMatchObject({ search: 'reset', createdBy: 1 })
        expect(router.values.searchParams).toMatchObject({ search: 'reset' })
    })

    it('saves two quick tag edits as one write that keeps both tags', async () => {
        const reset = logic.values.filteredTransactionalTemplates.find((t) => t.name === 'Password reset')!

        logic.actions.saveTransactionalTags(reset, ['auth', 'security'])
        const shown = logic.values.filteredTransactionalTemplates.find((t) => t.name === 'Password reset')!
        logic.actions.saveTransactionalTags(shown, [...shown.tags!, 'urgent'])
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([{ id: 'a', tags: ['auth', 'security', 'urgent'] }])
    })

    it('saves tag edits made on two rows within the same pause', async () => {
        const [reset, receipt] = ['Password reset', 'Receipt'].map(
            (name) => logic.values.transactionalTemplates.find((t) => t.name === name)!
        )

        logic.actions.saveTransactionalTags(reset, ['auth', 'security'])
        logic.actions.saveTransactionalTags(receipt, ['billing', 'urgent'])
        await expectLogic(logic).toFinishAllListeners()

        expect(writes).toEqual([
            { id: 'a', tags: ['auth', 'security'] },
            { id: 'b', tags: ['billing', 'urgent'] },
        ])
    })
})
