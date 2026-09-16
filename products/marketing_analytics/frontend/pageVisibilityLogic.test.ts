import { router } from 'kea-router'

import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { initKeaTests } from '~/test/init'

import { pageVisibilityLogic } from './pageVisibilityLogic'

describe('pageVisibilityLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        const posthog = jest.requireMock('posthog-js').default
        posthog.setPersonProperties = jest.fn()
        initKeaTests()
        webAnalyticsLogic.mount()
        pageVisibilityLogic.mount()
        router.actions.push('/marketing', { tab: 'page-visibility' })
    })

    afterEach(() => {
        pageVisibilityLogic.unmount()
        webAnalyticsLogic.unmount()
    })

    it('keeps marketing page visibility filters separate from web analytics', () => {
        webAnalyticsLogic.actions.setDates('-30d', null)
        webAnalyticsLogic.actions.setDeviceTypeFilter('Desktop')

        router.actions.push('/marketing', {
            tab: 'page-visibility',
            date_from: '-14d',
            device_type: 'Mobile',
        })

        expect(pageVisibilityLogic.values.dateFilter.dateFrom).toBe('-14d')
        expect(pageVisibilityLogic.values.deviceTypeFilter).toBe('Mobile')
        expect(webAnalyticsLogic.values.dateFilter.dateFrom).toBe('-30d')
        expect(webAnalyticsLogic.values.deviceTypeFilter).toBe('Desktop')

        pageVisibilityLogic.actions.setDates('-7d', null)

        expect(router.values.searchParams).toMatchObject({
            tab: 'page-visibility',
            date_from: '-7d',
            device_type: 'Mobile',
        })
    })
})
