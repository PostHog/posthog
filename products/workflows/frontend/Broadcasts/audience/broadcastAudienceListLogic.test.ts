import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { broadcastAudienceListLogic } from './broadcastAudienceListLogic'

describe('broadcastAudienceListLogic', () => {
    let createdCohorts: number

    beforeEach(() => {
        createdCohorts = 0
        useMocks({
            get: {
                '/api/projects/:team/cohorts/:id/': {
                    id: 42,
                    name: 'Spring sale recipients',
                    is_static: true,
                    is_calculating: true,
                },
            },
            post: {
                '/api/projects/:team/cohorts/': () => {
                    createdCohorts += 1
                    return [201, { id: 42, name: 'Spring sale recipients', is_static: true, is_calculating: true }]
                },
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }],
            },
        })
        initKeaTests()
        broadcastWizardLogic({ id: 'new' }).mount()
    })

    it('saves a pasted list as a cohort and adds it to the audience', async () => {
        const logic = broadcastAudienceListLogic({ id: 'new' })
        logic.mount()
        logic.actions.openListModal()
        logic.actions.setPastedText('ada@example.com\ngrace@example.com')

        await expectLogic(logic, () => {
            logic.actions.createListCohort()
        })
            .toDispatchActions(['createListCohortFinished', 'closeListModal'])
            .toMatchValues({ isListModalOpen: false, createError: null })

        expect(createdCohorts).toEqual(1)
        expect(broadcastWizardLogic({ id: 'new' }).values.audienceProperties).toEqual([
            {
                type: PropertyFilterType.Cohort,
                key: 'id',
                value: 42,
                operator: PropertyOperator.In,
                cohort_name: 'Spring sale recipients',
            },
        ])
    })

    it('creates no cohort for a CSV the import would reject', async () => {
        const logic = broadcastAudienceListLogic({ id: 'new' })
        logic.mount()
        logic.actions.openListModal()
        logic.actions.setSource('upload')
        logic.actions.setFile(new File(['name,company\nAda,Acme\n'], 'people.csv', { type: 'text/csv' }))

        await expectLogic(logic, () => {
            logic.actions.createListCohort()
        })
            .toDispatchActions(['createListCohortFinished'])
            .toMatchValues({
                isListModalOpen: true,
                createError: 'The file needs a column named email, distinct_id or person_id.',
            })

        expect(createdCohorts).toEqual(0)
        expect(broadcastWizardLogic({ id: 'new' }).values.audienceProperties).toEqual([])
    })
})
