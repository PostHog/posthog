import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { personDeleteModalLogic } from './personDeleteModalLogic'

const PERSON: PersonType = {
    id: '123',
    uuid: 'abc-123',
    distinct_ids: ['user@example.com'],
    properties: {},
    created_at: '2024-01-01T00:00:00Z',
}

describe('personDeleteModalLogic', () => {
    let logic: ReturnType<typeof personDeleteModalLogic.build>
    let deletedUrl: URL | null

    beforeEach(() => {
        deletedUrl = null
        useMocks({
            delete: {
                '/api/projects/:team_id/persons/:id/': ({ request }) => {
                    deletedUrl = new URL(request.url)
                    return [204]
                },
            },
        })
        initKeaTests()
        logic = personDeleteModalLogic({ person: PERSON })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        [false, ''],
        [true, '?delete_events=true'],
    ])('deletes the person on the project route with deleteEvents=%s', async (deleteEvents, expectedSearch) => {
        await expectLogic(logic, () => {
            logic.actions.deletePerson(PERSON, deleteEvents, false)
        }).toDispatchActions(['deletePersonSuccess'])

        expect(deletedUrl?.pathname).toEqual('/api/projects/997/persons/123/')
        expect(deletedUrl?.search).toEqual(expectedSearch)
    })
})
