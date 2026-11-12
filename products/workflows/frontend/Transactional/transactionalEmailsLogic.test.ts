import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MessageTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailsLogic } from './transactionalEmailsLogic'

const SERVER_PAGE_SIZE = 2

const template = (
    id: string,
    name: string,
    tags: string[],
    createdBy: number,
    transactional = true
): MessageTemplateApi =>
    ({
        id,
        name,
        description: '',
        tags,
        created_by: { id: createdBy },
        transactional_hog_flow_id: transactional ? `flow-${id}` : null,
        content: { templating: 'liquid', email: { subject: name, html: `<p>${name}</p>` } },
        draft_content: null,
        has_draft: false,
    }) as unknown as MessageTemplateApi

const STORED_TEMPLATES = [
    template('a', 'Password reset', ['auth'], 1),
    template('b', 'Receipt', ['billing'], 2),
    template('c', 'Sign-in code', ['auth'], 2),
    template('d', 'Newsletter', ['auth'], 1, false),
]

describe('transactionalEmailsLogic', () => {
    let logic: ReturnType<typeof transactionalEmailsLogic.build>
    let writes: { id: string; tags: string[] }[]
    let serverFiltersTransactional: boolean

    beforeEach(async () => {
        writes = []
        serverFiltersTransactional = true
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
                '/api/projects/:team_id/messaging_templates/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const offset = Number(params.get('offset') ?? 0)
                    const limit = Math.min(Number(params.get('limit') ?? SERVER_PAGE_SIZE), SERVER_PAGE_SIZE)
                    const matching = STORED_TEMPLATES.filter(
                        (t) =>
                            !serverFiltersTransactional ||
                            params.get('transactional') !== 'true' ||
                            t.transactional_hog_flow_id
                    ).map(({ content, draft_content, ...basic }) =>
                        params.get('basic') === 'true' ? basic : { ...basic, content, draft_content }
                    )
                    return [200, { count: matching.length, results: matching.slice(offset, offset + limit) }]
                },
            },
        })
        initKeaTests()
        logic = transactionalEmailsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    it.each([
        ['filters', true],
        ['ignores, as a server that predates it does,', false],
    ])(
        'loads every page of transactional emails without their content when the server %s the filter',
        async (_case, filters) => {
            serverFiltersTransactional = filters
            logic.actions.loadTransactionalTemplates()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.transactionalTemplates.map(({ name, content }) => ({ name, content }))).toEqual([
                { name: 'Password reset', content: undefined },
                { name: 'Receipt', content: undefined },
                { name: 'Sign-in code', content: undefined },
            ])
        }
    )

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
