import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

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
    let deleteSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        deleteSpy = jest.spyOn(api, 'delete').mockResolvedValue(undefined)
        logic = personDeleteModalLogic({ person: PERSON })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        deleteSpy.mockRestore()
    })

    it.each([
        [false, '/api/projects/997/persons/123/?'],
        [true, '/api/projects/997/persons/123/?delete_events=true'],
    ])('deletes the person on the project route with deleteEvents=%s', async (deleteEvents, expectedUrl) => {
        await expectLogic(logic, () => {
            logic.actions.deletePerson(PERSON, deleteEvents, false)
        }).toDispatchActions(['deletePersonSuccess'])

        expect(deleteSpy).toHaveBeenCalledWith(expectedUrl)
    })
})
