import { initKeaTests } from '~/test/init'

import { tracingFiltersLogic } from './tracingFiltersLogic'

describe('tracingFiltersLogic', () => {
    let logic: ReturnType<typeof tracingFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = tracingFiltersLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('view mode', () => {
        it('defaults to traces', () => {
            expect(logic.values.viewMode).toBe('traces')
            expect(logic.values.filters.viewMode).toBe('traces')
        })

        it('switches to spans', () => {
            logic.actions.setViewMode('spans')
            expect(logic.values.viewMode).toBe('spans')
            expect(logic.values.filters.viewMode).toBe('spans')
        })

        it('switches back to traces', () => {
            logic.actions.setViewMode('spans')
            logic.actions.setViewMode('traces')
            expect(logic.values.viewMode).toBe('traces')
        })
    })
})
