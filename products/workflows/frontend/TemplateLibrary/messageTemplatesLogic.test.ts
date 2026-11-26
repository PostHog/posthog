import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    TEMPLATE_SEARCH_MAX_LENGTH,
    TEMPLATES_PAGE_SIZE,
    messageTemplatesLogic,
    saveTemplateTags,
} from './messageTemplatesLogic'
import type { MessageTemplate } from './types'

const template = (id: string, name: string, tags: string[]): MessageTemplate =>
    ({ id, name, description: '', tags }) as unknown as MessageTemplate

describe('messageTemplatesLogic', () => {
    let logic: ReturnType<typeof messageTemplatesLogic.build>
    let stored: MessageTemplate[]
    let everything: MessageTemplate[] | null
    let requests: URLSearchParams[]
    let holdNextPages: boolean
    let heldNextPages: ((status: number) => void)[]

    const names = (): string[] => logic.values.templates.map((t) => t.name)
    const many = (count: number, prefix: string): MessageTemplate[] =>
        Array.from({ length: count }, (_, i) => template(`${prefix}${i}`, `${prefix} ${i}`, []))
    const remount = async (): Promise<void> => {
        logic.unmount()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
    }

    beforeEach(() => {
        everything = null
        stored = [
            template('a', 'Welcome', ['growth', 'onboarding']),
            template('b', 'Invoice', ['billing']),
            template('c', 'Plain', []),
        ]
        requests = []
        holdNextPages = false
        heldNextPages = []
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': async ({ request }) => {
                    const query = new URL(request.url).searchParams
                    requests.push(query)
                    const offset = Number(query.get('offset') ?? 0)
                    const limit = Number(query.get('limit'))
                    const filtered = ['search', 'created_by', 'tags', 'transactional'].some((key) => query.has(key))
                    const rows = filtered || !everything ? stored : everything
                    const next = offset + limit < rows.length ? `?offset=${offset + limit}` : null
                    const page = { count: rows.length, next, results: rows.slice(offset, offset + limit) }
                    const status =
                        offset > 0 && holdNextPages
                            ? await new Promise<number>((release) => heldNextPages.push(release))
                            : 200
                    return status === 200 ? [200, page] : [status, { detail: 'failed' }]
                },
            },
        })
        initKeaTests()
        logic = messageTemplatesLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each([
        ['creator', () => logic.actions.setCreatedByFilter(7), 'created_by=7'],
        ['tags', () => logic.actions.setTagsFilter(['growth', 'billing']), 'tags=growth&tags=billing'],
        ['transactional only', () => logic.actions.setTransactionalOnly(true), 'transactional=true'],
    ])('asks the server for the first page that matches the %s filter', async (_name, filter, query) => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        stored = [template('b', 'Invoice', ['billing'])]

        filter()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(requests.at(-1)?.toString()).toEqual(`limit=${TEMPLATES_PAGE_SIZE}&${query}`)
        expect(names()).toEqual(['Invoice'])
        expect(logic.values.hasActiveFilters).toBe(true)
    })

    it('asks the server once the search pauses', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        jest.useFakeTimers()
        try {
            logic.actions.setSearch('inv')
            await jest.advanceTimersByTimeAsync(200)
            logic.actions.setSearch('invoice ')
            await jest.advanceTimersByTimeAsync(299)
            expect(requests).toHaveLength(1)
            await jest.advanceTimersByTimeAsync(1)
        } finally {
            jest.useRealTimers()
        }
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(requests.map((query) => query.get('search'))).toEqual([null, 'invoice'])
    })

    it('loads the next page after the templates already shown, until the server has no more', async () => {
        stored = Array.from({ length: TEMPLATES_PAGE_SIZE + 2 }, (_, i) => template(`t${i}`, `Template ${i}`, []))
        logic.unmount()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        expect(logic.values).toMatchObject({ hasMoreTemplates: true, moreTemplatesLoading: false })
        expect(names()).toHaveLength(TEMPLATES_PAGE_SIZE)

        logic.actions.loadMoreTemplates()
        await expectLogic(logic).toDispatchActions(['loadMoreTemplatesSuccess'])

        expect(requests.at(-1)?.get('offset')).toEqual(String(TEMPLATES_PAGE_SIZE))
        expect(names()).toEqual(stored.map((t) => t.name))
        expect(logic.values).toMatchObject({ hasMoreTemplates: false, moreTemplatesLoading: false })
    })

    it.each([
        ['before', () => logic.actions.loadMoreTemplates(), () => logic.actions.setCreatedByFilter(7), 1],
        ['after', () => logic.actions.setCreatedByFilter(7), () => logic.actions.loadMoreTemplates(), 0],
    ])('drops a next page asked for %s the filters changed', async (_order, first, second, nextPagesSent) => {
        stored = many(TEMPLATES_PAGE_SIZE + 1, 'Old')
        await remount()
        holdNextPages = true

        first()
        stored = many(TEMPLATES_PAGE_SIZE + 2, 'New')
        second()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        await waitFor(() => expect(heldNextPages).toHaveLength(nextPagesSent))
        heldNextPages.forEach((release) => release(200))
        await expectLogic(logic).toFinishAllListeners()

        expect(names()).toEqual(stored.slice(0, TEMPLATES_PAGE_SIZE).map((t) => t.name))
        expect(logic.values).toMatchObject({ hasMoreTemplates: true, moreTemplatesLoading: false })
    })

    it('keeps loading the current next page when an outdated one fails', async () => {
        stored = many(TEMPLATES_PAGE_SIZE + 1, 'Old')
        await remount()
        holdNextPages = true
        logic.actions.loadMoreTemplates()
        stored = many(TEMPLATES_PAGE_SIZE + 2, 'New')
        logic.actions.setCreatedByFilter(7)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        logic.actions.loadMoreTemplates()
        await waitFor(() => expect(heldNextPages).toHaveLength(2))

        heldNextPages[0](500)
        heldNextPages[1](200)
        await expectLogic(logic).toDispatchActions(['loadMoreTemplatesSuccess'])

        expect(names()).toEqual(stored.map((t) => t.name))
    })

    it('keeps counting every template under a filter, and reloads the filtered list after a create', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        everything = [...stored]
        stored = []
        logic.actions.setCreatedByFilter(7)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        expect(logic.values.templateCount).toBe(3)

        const created = template('d', 'Fresh', [])
        useMocks({
            post: {
                '/api/projects/:team_id/messaging_templates/': () => {
                    everything = [created, ...(everything ?? [])]
                    return [201, created]
                },
            },
        })
        logic.actions.createTemplate({ template: { name: 'Fresh' } })
        await expectLogic(logic).toDispatchActions(['createTemplateSuccess', 'loadTemplatesSuccess'])
        await expectLogic(logic).toFinishAllListeners()

        expect(names()).toEqual([])
        expect(logic.values.templateCount).toBe(4)
    })

    it('cuts a long search to what the server accepts', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        logic.actions.setSearch('x'.repeat(TEMPLATE_SEARCH_MAX_LENGTH + 50))
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(requests.at(-1)?.get('search')).toEqual('x'.repeat(TEMPLATE_SEARCH_MAX_LENGTH))
    })

    it('saves a tag edit with only the tags, so it never republishes the content', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const bodies: unknown[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, template('a', 'Welcome', ['growth'])]
                },
            },
        })

        await saveTemplateTags(template('a', 'Welcome', []), ['growth'])

        expect(bodies).toEqual([{ tags: ['growth'] }])
        expect(logic.values.templates.find((t) => t.id === 'a')?.tags).toEqual(['growth'])
    })

    it('reloads a tag-filtered list after a tag edit, so a template that left the filter goes away', async () => {
        logic.actions.setTagsFilter(['growth'])
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': () => [200, template('a', 'Welcome', [])],
            },
        })
        stored = []

        await saveTemplateTags(template('a', 'Welcome', ['growth']), [])
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(names()).toEqual([])
    })

    it('rejects a failed tag save, so the editor it was opened from stays open', async () => {
        await expectLogic(logic).toFinishAllListeners()
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id/': () => [400, { detail: 'too many tags' }],
            },
        })

        await expect(saveTemplateTags(template('a', 'Welcome', []), ['growth'])).rejects.toThrow()
        expect(logic.values.templates.find((t) => t.id === 'a')?.tags).toEqual(['growth', 'onboarding'])
    })
})
