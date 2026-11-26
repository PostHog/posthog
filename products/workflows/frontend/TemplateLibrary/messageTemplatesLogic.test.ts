import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TEMPLATES_PAGE_SIZE, messageTemplatesLogic, saveTemplateTags } from './messageTemplatesLogic'
import type { MessageTemplate } from './types'

const template = (id: string, name: string, tags: string[]): MessageTemplate =>
    ({ id, name, description: '', tags }) as unknown as MessageTemplate

describe('messageTemplatesLogic', () => {
    let logic: ReturnType<typeof messageTemplatesLogic.build>
    let stored: MessageTemplate[]
    let requests: URLSearchParams[]
    let nextPageHeld: Promise<void> | null

    const names = (): string[] => logic.values.templates.map((t) => t.name)

    beforeEach(() => {
        stored = [
            template('a', 'Welcome', ['growth', 'onboarding']),
            template('b', 'Invoice', ['billing']),
            template('c', 'Plain', []),
        ]
        requests = []
        nextPageHeld = null
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': async ({ request }) => {
                    const query = new URL(request.url).searchParams
                    requests.push(query)
                    const offset = Number(query.get('offset') ?? 0)
                    const limit = Number(query.get('limit'))
                    const next = offset + limit < stored.length ? `?offset=${offset + limit}` : null
                    const page = { count: stored.length, next, results: stored.slice(offset, offset + limit) }
                    if (offset > 0 && nextPageHeld) {
                        await nextPageHeld
                    }
                    return [200, page]
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

    it('drops a next page that arrives after the filters changed', async () => {
        stored = Array.from({ length: TEMPLATES_PAGE_SIZE + 1 }, (_, i) => template(`t${i}`, `Template ${i}`, []))
        logic.unmount()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])

        let releaseNextPage = (): void => {}
        nextPageHeld = new Promise((resolve) => {
            releaseNextPage = resolve
        })
        logic.actions.loadMoreTemplates()
        await waitFor(() => expect(requests.at(-1)?.get('offset')).toEqual(String(TEMPLATES_PAGE_SIZE)))
        stored = [template('b', 'Invoice', ['billing'])]
        logic.actions.setCreatedByFilter(7)
        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        releaseNextPage()
        await expectLogic(logic).toFinishAllListeners()

        expect(names()).toEqual(['Invoice'])
        expect(logic.values.moreTemplatesLoading).toBe(false)
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
