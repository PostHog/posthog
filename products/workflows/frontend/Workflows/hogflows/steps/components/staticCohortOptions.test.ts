import { staticCohortOptions } from './staticCohortOptions'

describe('staticCohortOptions', () => {
    it('shows only active static cohorts', () => {
        const cohorts = [
            { id: 1, name: 'Static', is_static: true, deleted: false },
            { id: 2, name: 'Dynamic', is_static: false, deleted: false },
            { id: 3, name: 'Deleted', is_static: true, deleted: true },
        ]

        expect(staticCohortOptions(cohorts)).toEqual([{ key: '1', value: 1, label: 'Static' }])
    })
})
