import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CohortType } from '~/types'

import { batchAudienceCsvLogic, cohortNameFromFile } from './batchAudienceCsvLogic'

describe('batchAudienceCsvLogic', () => {
    let logic: ReturnType<typeof batchAudienceCsvLogic.build>
    let onCohortCreated: jest.Mock
    let postedBody: FormData | null

    beforeEach(() => {
        postedBody = null
        onCohortCreated = jest.fn()
        useMocks({
            post: {
                '/api/projects/:team_id/cohorts/': async (req) => {
                    postedBody = (await req.request.formData()) as FormData
                    return [201, { id: 7, name: 'launch-list' } as CohortType]
                },
            },
        })
        initKeaTests()
        logic = batchAudienceCsvLogic({ id: 'trigger_1', onCohortCreated })
        logic.mount()
    })

    it.each([
        ['launch-list.csv', 'launch-list'],
        ['launch-list', 'launch-list'],
        ['.csv', 'Uploaded list'],
    ])('names the cohort after the file %j', (fileName, expected) => {
        expect(cohortNameFromFile(fileName)).toBe(expected)
    })

    it('uploads the file as a static cohort and hands it to the audience', async () => {
        logic.actions.uploadCsv(new File(['a@example.com'], 'launch-list.csv', { type: 'text/csv' }))

        await expectLogic(logic).toDispatchActions(['uploadCsvSuccess'])

        const body = postedBody as unknown as FormData
        expect(body.get('is_static')).toBe('true')
        expect(body.get('name')).toBe('launch-list')
        expect((body.get('csv') as File).name).toBe('launch-list.csv')
        expect(onCohortCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }))
    })
})
