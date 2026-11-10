import { initKeaTests } from '~/test/init'

import { HOME_TAB_DEFAULT_DATE_RANGE, homeTabDefaultLogic } from './homeTabDefaultLogic'

describe('homeTabDefaultLogic', () => {
    beforeEach(() => {
        initKeaTests()
        homeTabDefaultLogic.mount()
    })

    afterEach(() => {
        homeTabDefaultLogic.unmount()
    })

    it('keeps the chosen range, exact-date setting, and comparison', () => {
        expect(homeTabDefaultLogic.values.dateRange).toEqual(HOME_TAB_DEFAULT_DATE_RANGE)
        expect(homeTabDefaultLogic.values.compare).toBe(true)
        expect(homeTabDefaultLogic.values.selectedMetric).toBe('active_users')
        expect(homeTabDefaultLogic.values.selectedContentKey).toBe('top_pages')

        homeTabDefaultLogic.actions.setDates('2026-08-01T12:00:00Z', '2026-08-31T12:00:00Z', true)
        homeTabDefaultLogic.actions.setCompare(false)
        homeTabDefaultLogic.actions.setSelectedMetric('sessions')
        homeTabDefaultLogic.actions.setSelectedContentKey('top_screens')

        expect(homeTabDefaultLogic.values.dateRange).toEqual({
            date_from: '2026-08-01T12:00:00Z',
            date_to: '2026-08-31T12:00:00Z',
            explicitDate: true,
        })
        expect(homeTabDefaultLogic.values.compare).toBe(false)
        expect(homeTabDefaultLogic.values.selectedMetric).toBe('sessions')
        expect(homeTabDefaultLogic.values.selectedContentKey).toBe('top_screens')
    })
})
