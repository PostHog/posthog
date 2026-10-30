import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastsLogic } from './broadcastsLogic'

describe('broadcastsLogic', () => {
    let logic: ReturnType<typeof broadcastsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flows/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        logic = broadcastsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('keeps the filters when a link back to the list carries no query params', () => {
        router.actions.push('/broadcasts?status=sent&search=welcome')
        expect(logic.values.filters.status).toEqual('sent')

        router.actions.push('/broadcasts')

        expect(logic.values.filters.status).toEqual('sent')
        expect(logic.values.filters.search).toEqual('welcome')
        expect(router.values.searchParams).toMatchObject({ status: 'sent', search: 'welcome' })
    })

    it('defaults the tags filter when the saved filters have none', () => {
        logic.actions.setFilters({ search: 'welcome' })
        const key = Object.keys(localStorage).find((k) => k.includes('broadcasts_list_filters'))!
        const { tags: _, ...savedBeforeTags } = JSON.parse(localStorage.getItem(key)!)
        localStorage.setItem(key, JSON.stringify(savedBeforeTags))
        logic.unmount()
        router.actions.push('/broadcasts')

        logic = broadcastsLogic()
        logic.mount()

        expect(logic.values.filters).toMatchObject({ search: 'welcome', tags: [] })
    })
})
