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
    let holdCounts: boolean
    let holdFirstPages: boolean
    let heldFirstPages: ((status: number) => void)[]
    let heldCounts: ((status: number) => void)[]

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
        holdCounts = false
        heldCounts = []
        holdFirstPages = false
        heldFirstPages = []
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': async ({ request }) => {
                    const query = new URL(request.url).searchParams
                    const offset = Number(query.get('offset') ?? 0)
                    const limit = Number(query.get('limit'))
                    if (limit > 1) {
                        requests.push(query)
                    }
                    const filtered = ['search', 'created_by', 'tags', 'transactional'].some((key) => query.has(key))
                    const rows = filtered || !everything ? stored : everything
                    const next = offset + limit < rows.length ? `?offset=${offset + limit}` : null
                    const page = { count: rows.length, next, results: rows.slice(offset, offset + limit) }
                    const held =
                        offset > 0 && holdNextPages
                            ? heldNextPages
                            : limit === 1 && holdCounts
                              ? heldCounts
                              : offset === 0 && limit > 1 && holdFirstPages
                                ? heldFirstPages
                                : null
                    const status = held ? await new Promise<number>((release) => held.push(release)) : 200
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

    it('counts the templates even when a filter is set before the first page lands', async () => {
        logic.actions.setCreatedByFilter(7)
        await expectLogic(logic).toFinishAllListeners()
        await waitFor(() => expect(logic.values.templateCount).toBe(3))
    })

    it('keeps the newest template count when an older count answers last', async () => {
        await expectLogic(logic).toFinishAllListeners()
        holdCounts = true
        logic.actions.loadTemplateCount()
        await waitFor(() => expect(heldCounts).toHaveLength(1))
        holdCounts = false
        stored = [...stored, template('d', 'Fresh', [])]
        logic.actions.loadTemplateCount()
        await waitFor(() => expect(logic.values.templateCount).toBe(4))

        heldCounts[0](200)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.templateCount).toBe(4)
    })

    it('shows a duplicate once when the filter clears before the duplicate answers', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        everything = [...stored]
        stored = [stored[0]]
        logic.actions.setCreatedByFilter(7)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        const copy = template('d', 'Welcome (copy)', [])
        let answerDuplicate = (): void => {}
        useMocks({
            post: {
                '/api/projects/:team_id/messaging_templates/': async () => {
                    everything = [copy, ...(everything ?? [])]
                    await new Promise<void>((release) => (answerDuplicate = release))
                    return [201, copy]
                },
            },
        })

        logic.actions.duplicateTemplate(stored[0])
        await waitFor(() => expect(everything).toHaveLength(4))
        logic.actions.setCreatedByFilter(null)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        answerDuplicate()
        await expectLogic(logic).toDispatchActions(['duplicateTemplateSuccess'])

        await waitFor(() => expect(names()).toEqual(['Welcome (copy)', 'Welcome', 'Invoice', 'Plain']))
    })

    it('keeps a template deleted while a reload is in flight out of the reloaded list', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        const copy = template('d', 'Welcome (copy)', [])
        const deleteTemplate = (): [number, object] => {
            stored = stored.filter((t) => t.id !== 'b')
            return [200, { id: 'b', deleted: true }]
        }
        useMocks({
            post: {
                '/api/projects/:team_id/messaging_templates/': () => {
                    stored = [copy, ...stored]
                    return [201, copy]
                },
            },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id': deleteTemplate,
                '/api/environments/:team_id/messaging_templates/:id/': deleteTemplate,
            },
        })
        holdFirstPages = true

        logic.actions.duplicateTemplate(stored[0])
        await waitFor(() => expect(heldFirstPages).toHaveLength(1))
        logic.actions.deleteTemplate(stored.find((t) => t.id === 'b')!)
        await waitFor(() => expect(stored.map((t) => t.id)).not.toContain('b'))
        await expectLogic(logic).toDispatchActions(['deleteTemplateSuccess'])
        heldFirstPages[0](200)

        await waitFor(() => expect(names()).toEqual(['Welcome (copy)', 'Welcome', 'Plain']))
    })

    it('counts no templates when the count and the list fail, and takes the count from the list once it reloads', async () => {
        holdCounts = true
        holdFirstPages = true
        logic.unmount()
        logic.mount()
        await waitFor(() => expect(heldCounts).toHaveLength(1))
        await waitFor(() => expect(heldFirstPages).toHaveLength(1))

        heldCounts[0](500)
        heldFirstPages[0](500)
        await waitFor(() => expect(logic.values.canRetryTemplates).toBe(true))
        await waitFor(() => expect(logic.values.templateCount).toBe(0))

        holdFirstPages = false
        logic.actions.loadTemplates()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(logic.values.templateCount).toBe(3)
    })

    it('keeps paging off after a filtered create until the reloaded first page lands', async () => {
        stored = many(TEMPLATES_PAGE_SIZE + 1, 'Match')
        logic.actions.setCreatedByFilter(7)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        expect(logic.values.canLoadMoreTemplates).toBe(true)
        useMocks({
            post: { '/api/projects/:team_id/messaging_templates/': () => [201, template('d', 'Fresh', [])] },
        })
        holdFirstPages = true

        logic.actions.createTemplate({ template: { name: 'Fresh' } })
        await expectLogic(logic).toDispatchActions(['createTemplateSuccess'])
        await waitFor(() => expect(heldFirstPages).toHaveLength(1))
        expect(logic.values.canLoadMoreTemplates).toBe(false)

        heldFirstPages[0](200)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        expect(logic.values.canLoadMoreTemplates).toBe(true)
        expect(names()).toEqual(stored.slice(0, TEMPLATES_PAGE_SIZE).map((t) => t.name))
    })

    it.each([
        ['after a create', () => logic.actions.createTemplate({ template: { name: 'Fresh' } })],
        ['under unchanged filters', () => logic.actions.loadTemplates()],
    ])('offers a retry when the reload %s fails, and pages again once it lands', async (_name, reload) => {
        stored = many(TEMPLATES_PAGE_SIZE + 1, 'Match')
        await remount()
        useMocks({
            post: { '/api/projects/:team_id/messaging_templates/': () => [201, template('d', 'Fresh', [])] },
        })
        holdFirstPages = true

        reload()
        await waitFor(() => expect(heldFirstPages).toHaveLength(1))
        heldFirstPages[0](500)
        await expectLogic(logic).toDispatchActions(['loadTemplatesFailure'])
        expect(logic.values.canLoadMoreTemplates).toBe(false)
        expect(logic.values.canRetryTemplates).toBe(true)

        holdFirstPages = false
        logic.actions.loadTemplates()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(logic.values.canRetryTemplates).toBe(false)
        expect(logic.values.canLoadMoreTemplates).toBe(true)
    })

    it('keeps tags saved while the reload after a duplicate is in flight', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        const copy = template('d', 'Welcome (copy)', [])
        const saveTags = async ({
            request,
            params,
        }: {
            request: Request
            params: Record<string, any>
        }): Promise<[number, MessageTemplate | undefined]> => {
            const { tags } = (await request.json()) as { tags: string[] }
            stored = stored.map((t) => (t.id === params.id ? { ...t, tags } : t))
            return [200, stored.find((t) => t.id === params.id)]
        }
        useMocks({
            post: {
                '/api/projects/:team_id/messaging_templates/': () => {
                    stored = [copy, ...stored]
                    return [201, copy]
                },
            },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id': saveTags,
                '/api/environments/:team_id/messaging_templates/:id/': saveTags,
            },
        })
        holdFirstPages = true

        logic.actions.duplicateTemplate(stored[0])
        await waitFor(() => expect(heldFirstPages).toHaveLength(1))
        await expectLogic(logic).toDispatchActions(['duplicateTemplateSuccess'])
        holdFirstPages = false
        await saveTemplateTags(stored.find((t) => t.id === 'c')!, ['vip'])
        heldFirstPages[0](200)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(logic.values.templates.find((t) => t.id === 'c')?.tags).toEqual(['vip'])
    })

    it('offers no retry when a first page for outdated filters fails after the current one loaded', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        stored = many(TEMPLATES_PAGE_SIZE + 1, 'Match')
        holdFirstPages = true
        logic.actions.setCreatedByFilter(7)
        await waitFor(() => expect(heldFirstPages).toHaveLength(1))
        logic.actions.setCreatedByFilter(8)
        await waitFor(() => expect(heldFirstPages).toHaveLength(2))

        heldFirstPages[1](200)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        heldFirstPages[0](500)
        logic.actions.loadMoreTemplates()
        await expectLogic(logic).toDispatchActions(['loadMoreTemplatesSuccess'])

        expect(logic.values.canRetryTemplates).toBe(false)
        expect(names()).toEqual(stored.map((t) => t.name))
    })

    it('cuts a long search to what the server accepts, without splitting an emoji', async () => {
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        const accepted = 'x'.repeat(TEMPLATE_SEARCH_MAX_LENGTH - 1) + '😀'

        logic.actions.setSearch(accepted + 'y'.repeat(50))
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        expect(requests.at(-1)?.get('search')).toEqual(accepted)
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
