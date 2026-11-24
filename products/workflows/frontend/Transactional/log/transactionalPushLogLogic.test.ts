import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { transactionalEmailLogLogic } from './transactionalEmailLogLogic'
import { transactionalEmailLogSearchLogic } from './transactionalEmailLogSearchLogic'
import { transactionalPushLogLogic } from './transactionalPushLogLogic'

describe('transactionalPushLogLogic', () => {
    let logic: ReturnType<typeof transactionalPushLogLogic.build>
    let emailRequests: number
    let pushRequests: Record<string, string>[]

    beforeEach(async () => {
        emailRequests = 0
        pushRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/': () => {
                    emailRequests++
                    return [200, { results: [], has_more: false }]
                },
                '/api/projects/:team_id/transactional_push_log/': ({ request }) => {
                    pushRequests.push(Object.fromEntries(new URL(request.url).searchParams))
                    return [200, { results: [], has_more: false }]
                },
            },
        })
        initKeaTests()
        router.actions.push('/transactional/log', { channel: 'push', status: 'bounced' })
        logic = transactionalPushLogLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    it('loads only pushes, on open and when the dates change', async () => {
        logic.actions.setFilters({ dateFrom: '-1d', dateTo: null })
        await expectLogic(logic).toFinishAllListeners()

        expect(pushRequests).toHaveLength(2)
        expect(emailRequests).toBe(0)
        expect(router.values.searchParams).toEqual({ channel: 'push', status: 'bounced', date_from: '-1d' })
    })

    it('leaves the email search in place while pushes show', async () => {
        const unmountSearch = transactionalEmailLogSearchLogic({}).mount()
        logic.unmount()
        const emailLog = transactionalEmailLogLogic()
        emailLog.mount()
        emailLog.actions.setFilters({ search: 'ada@example.com' })
        emailLog.unmount()
        logic.mount()
        logic.unmount()
        emailLog.mount()

        expect(emailLog.values.filters.search).toBe('ada@example.com')
        emailLog.unmount()
        unmountSearch()
        logic.mount()
    })

    it('hands its dates to the email log, and takes the ones the email log set', async () => {
        logic.actions.setFilters({ dateFrom: '-1d', dateTo: null })
        logic.unmount()
        const emailLog = transactionalEmailLogLogic()
        emailLog.mount()
        expect(emailLog.values.filters.dateFrom).toBe('-1d')

        emailLog.actions.setFilters({ dateFrom: '-3d' })
        emailLog.unmount()
        logic.mount()
        expect(logic.values.filters.dateFrom).toBe('-3d')
    })
})
