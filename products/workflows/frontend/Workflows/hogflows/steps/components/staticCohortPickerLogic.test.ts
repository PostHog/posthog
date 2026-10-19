import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'

import { staticCohortPickerLogic } from './staticCohortPickerLogic'

const cohort = (id: number, name: string): CohortApi => ({ id, name, is_static: true, deleted: false }) as CohortApi

describe('staticCohortPickerLogic', () => {
    beforeEach(() => {
        resetContext({ plugins: [testUtilsPlugin] })
        initKeaTests()
    })

    it('loads, paginates, and searches static cohorts on the server', async () => {
        const first = cohort(1, 'First')
        const next = cohort(2, 'Next')
        const match = cohort(3, 'Needle')
        const requests: URLSearchParams[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    if (params.get('search')) {
                        return [200, { results: [match], count: 1, next: null }]
                    }
                    if (params.get('offset') === '1') {
                        return [200, { results: [next], count: 2, next: null }]
                    }
                    return [200, { results: [first], count: 2, next: 'next-page' }]
                },
            },
        })

        const logic = staticCohortPickerLogic({ id: 'action-1', selectedCohortId: null })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadCohortPageSuccess'])
            .toMatchValues({
                visibleCohorts: [first],
                hasMoreCohorts: true,
            })

        await expectLogic(logic, () => logic.actions.loadMoreCohorts())
            .toDispatchActions(['loadCohortPageSuccess'])
            .toMatchValues({ visibleCohorts: [first, next], hasMoreCohorts: false })

        await expectLogic(logic, () => logic.actions.setSearchTerm('Needle'))
            .toDispatchActions(['loadCohortPageSuccess'])
            .toMatchValues({ visibleCohorts: [match] })

        expect(requests.map((params) => params.get('type'))).toEqual(['static', 'static', 'static'])
        expect(requests[1].get('offset')).toBe('1')
        expect(requests[2].get('search')).toBe('Needle')
    })

    it('loads the selected cohort when it is outside the first page', async () => {
        const first = cohort(1, 'First')
        const selected = cohort(99, 'Selected')
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': [200, { results: [first], count: 2, next: 'next-page' }],
                '/api/projects/:team_id/cohorts/:id/': [200, selected],
            },
        })

        const logic = staticCohortPickerLogic({ id: 'action-2', selectedCohortId: selected.id })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadCohortPageSuccess', 'loadCohortByIdSuccess'])
            .toMatchValues({ visibleCohorts: [first, selected] })
    })
})
