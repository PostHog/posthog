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

    it('saves an uploaded list as a cohort and adds it to the audience', async () => {
        const logic = broadcastAudienceListLogic({ id: 'new' })
        logic.mount()
        logic.actions.openListModal()
        logic.actions.setFile(
            new File(['email\nada@example.com\ngrace@example.com\n'], 'people.csv', { type: 'text/csv' })
        )

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

    it.each([
        {
            file: 'a CSV the import would reject',
            content: 'name,company\nAda,Acme\n',
            error: 'The file needs a column named email, distinct_id or person_id.',
        },
        {
            // "Zoë" in Windows-1252, which the cohort import can't decode after it saves the cohort.
            file: 'a CSV that is not UTF-8',
            content: new Uint8Array([
                ...new TextEncoder().encode('email\nzo'),
                0xeb,
                ...new TextEncoder().encode('@example.com\n'),
            ]),
            error: 'This file isn\'t saved as UTF-8. Save it as "CSV UTF-8" and upload it again.',
        },
    ])('creates no cohort for $file', async ({ content, error }) => {
        const logic = broadcastAudienceListLogic({ id: 'new' })
        logic.mount()
        logic.actions.openListModal()
        logic.actions.setFile(new File([content], 'people.csv', { type: 'text/csv' }))

        await expectLogic(logic, () => {
            logic.actions.createListCohort()
        })
            .toDispatchActions(['createListCohortFinished'])
            .toMatchValues({ isListModalOpen: true, createError: error })

        expect(createdCohorts).toEqual(0)
        expect(broadcastWizardLogic({ id: 'new' }).values.audienceProperties).toEqual([])
    })
})
