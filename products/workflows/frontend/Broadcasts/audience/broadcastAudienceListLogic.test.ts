import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { broadcastAudienceListLogic } from './broadcastAudienceListLogic'

describe('broadcastAudienceListLogic', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }],
            },
        })
        initKeaTests()
        broadcastWizardLogic({ id: 'new' }).mount()
    })

    const LIST_CSV = 'email,org\nada@example.com,Hedgebox\n'

    it.each([
        {
            outcome: 'saves a recipient list and makes it the audience',
            csv: LIST_CSV,
            response: [201, { id: 'list-1', row_count: 1, columns: ['email', 'org'] }] as [number, object],
            expected: { isListModalOpen: false, createError: null },
            filters: { audience_type: 'recipient_list', recipient_list_id: 'list-1', properties: [] },
        },
        {
            outcome: 'shows why the API rejected the list and keeps the audience',
            csv: LIST_CSV,
            response: [400, { detail: 'Add a column named "email".' }] as [number, object],
            expected: { isListModalOpen: true, createError: 'Couldn\'t save the list: Add a column named "email".' },
            filters: { properties: [] },
        },
        {
            // An extra cell would put values under the wrong columns, so nothing is sent to the API.
            outcome: 'rejects a row with too many cells and keeps the audience',
            csv: 'email,org\nada@example.com,Hedgebox,extra\n',
            response: [500, {}] as [number, object],
            expected: {
                isListModalOpen: true,
                createError: expect.stringContaining("Row 2 of the file can't be read"),
            },
            filters: { properties: [] },
        },
        {
            outcome: 'rejects two email columns and keeps the audience',
            csv: 'email,email\nada@example.com,grace@example.com\n',
            response: [500, {}] as [number, object],
            expected: {
                isListModalOpen: true,
                createError: 'Couldn\'t save the list: Two columns are both named "email". Rename one and try again.',
            },
            filters: { properties: [] },
        },
        {
            outcome: 'rejects two distinct_id columns, one quoted, and keeps the audience',
            csv: 'email,distinct_id,"distinct_id"\nada@example.com,user-1,user-2\n',
            response: [500, {}] as [number, object],
            expected: {
                isListModalOpen: true,
                createError:
                    'Couldn\'t save the list: Two columns are both named "distinct_id". Rename one and try again.',
            },
            filters: { properties: [] },
        },
    ])('an upload $outcome', async ({ csv, response, expected, filters }) => {
        useMocks({ post: { '/api/projects/:team_id/workflow_recipient_lists/': () => response } })
        const logic = broadcastAudienceListLogic({ id: 'new' })
        logic.mount()
        logic.actions.openListModal()
        logic.actions.setFile(new File([csv], 'people.csv'))

        await expectLogic(logic, () => {
            logic.actions.submitList()
        })
            .toDispatchActions(['submitListFinished'])
            .toMatchValues(expected)

        expect(broadcastWizardLogic({ id: 'new' }).values.audienceFilters).toEqual(filters)
    })
})
