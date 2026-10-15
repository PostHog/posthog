import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
            .toDispatchActions(['closeListModal', 'createListCohortFinished'])
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

    const SPRING_SALE_COHORT = {
        type: PropertyFilterType.Cohort,
        key: 'id',
        value: 42,
        operator: PropertyOperator.In,
        cohort_name: 'Spring sale recipients',
    }

    const IMPORTED = [
        201,
        {
            cohort_id: 42,
            row_count: 1,
            new_people: 1,
            columns: ['email'],
            dropped_invalid_email: 0,
            dropped_duplicate_email: 0,
            dropped_too_large: 0,
        },
    ]
    const ADDED = { isListModalOpen: false, createError: null }

    it.each([
        {
            outcome: 'imports the people and adds their cohort to the audience',
            csv: 'email,plan\nada@example.com,Pro\n',
            response: IMPORTED,
            expected: ADDED,
            audience: [SPRING_SALE_COHORT],
            importedRows: [{ email: 'ada@example.com', plan: 'Pro' }],
        },
        {
            outcome: 'keeps quoted column names that contain commas',
            csv: 'email,"Address, line 1","Address, line 2"\nada@example.com,1 Main St,Flat 2\n',
            response: IMPORTED,
            expected: ADDED,
            audience: [SPRING_SALE_COHORT],
            importedRows: [{ email: 'ada@example.com', 'Address, line 1': '1 Main St', 'Address, line 2': 'Flat 2' }],
        },
        {
            outcome: 'drops an empty column with no name',
            csv: 'email,\nada@example.com,\n',
            response: IMPORTED,
            expected: ADDED,
            audience: [SPRING_SALE_COHORT],
            importedRows: [{ email: 'ada@example.com' }],
        },
        {
            outcome: 'adds the cohort even when reading it back fails, so a retry cannot import twice',
            csv: 'email\nada@example.com\n',
            response: IMPORTED,
            cohortReadFails: true,
            expected: ADDED,
            audience: [SPRING_SALE_COHORT],
            importedRows: [{ email: 'ada@example.com' }],
        },
        {
            outcome: 'rejects a file that is not UTF-8',
            csv: new Uint8Array([
                ...new TextEncoder().encode('email\nzo'),
                0xeb,
                ...new TextEncoder().encode('@example.com\n'),
            ]),
            response: [500, {}],
            expected: {
                isListModalOpen: true,
                createError: 'This file isn\'t saved as UTF-8. Save it as "CSV UTF-8" and upload it again.',
            },
            audience: [],
            importedRows: undefined,
        },
        {
            outcome: 'rejects a column with data but no name',
            csv: 'email,\nada@example.com,Acme\n',
            response: [500, {}],
            expected: {
                isListModalOpen: true,
                createError: 'A column with data in it has no name. Name it and try again.',
            },
            audience: [],
            importedRows: undefined,
        },
        {
            outcome: 'shows why the API rejected the file and keeps the audience',
            csv: 'name\nAda\n',
            response: [400, { detail: 'Add a column named "email" with each person\'s address.' }],
            expected: {
                isListModalOpen: true,
                createError: 'Couldn\'t import the people: Add a column named "email" with each person\'s address.',
            },
            audience: [],
            importedRows: [{ name: 'Ada' }],
        },
        {
            // The two columns would collapse into one key, so the API could not see the repeat.
            outcome: 'rejects two email columns before sending anything',
            csv: '\nemail,email\nada@example.com,grace@example.com\n',
            response: [500, {}],
            expected: {
                isListModalOpen: true,
                createError: 'Two columns are both named "email". Rename one and try again.',
            },
            audience: [],
            importedRows: undefined,
        },
    ])(
        'with the people import flag on, an upload $outcome',
        async ({ csv, response, cohortReadFails, expected, audience, importedRows }) => {
            let sentRows: unknown
            useMocks({
                ...(cohortReadFails ? { get: { '/api/projects/:team/cohorts/:id/': () => [500, {}] } } : {}),
                post: {
                    '/api/projects/:team_id/workflow_people_imports/': async ({ request }) => {
                        sentRows = ((await request.json()) as { rows: unknown }).rows
                        return response as [number, object]
                    },
                },
            })
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_BROADCAST_RECIPIENT_LISTS], {
                [FEATURE_FLAGS.WORKFLOWS_BROADCAST_RECIPIENT_LISTS]: true,
            })
            const logic = broadcastAudienceListLogic({ id: 'new' })
            logic.mount()
            logic.actions.openListModal()
            logic.actions.setCohortName('Spring sale recipients')
            logic.actions.setFile(new File([csv], 'people.csv', { type: 'text/csv' }))

            await expectLogic(logic, () => {
                logic.actions.createListCohort()
            })
                .toDispatchActions(['createListCohortFinished'])
                .toMatchValues(expected)

            expect(sentRows).toEqual(importedRows)
            expect(createdCohorts).toEqual(0)
            expect(broadcastWizardLogic({ id: 'new' }).values.audienceProperties).toEqual(audience)
        }
    )
})
