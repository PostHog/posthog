import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { personDeleteModalLogic } from './personDeleteModalLogic'

const PERSON: PersonType = { id: '1', distinct_ids: ['abc'], properties: {} }
const OTHER_PERSON: PersonType = { id: '2', distinct_ids: ['xyz'], properties: {} }

describe('personDeleteModalLogic', () => {
    let logic: ReturnType<typeof personDeleteModalLogic.build>

    beforeEach(() => {
        useMocks({ delete: { '/api/person/:id': [200, {}] } })
        initKeaTests()
        logic = personDeleteModalLogic()
        logic.mount()
    })

    it('clears the confirmation form after a delete, so the next person is gated again', async () => {
        await expectLogic(logic, () => {
            logic.actions.showPersonDeleteModal(PERSON)
            logic.actions.setDeleteConfirmationText('delete')
            logic.actions.setAlsoDeleteEvents(true)
            logic.actions.setAlsoDeleteRecordings(true)
            logic.actions.deletePerson(PERSON, true, true)
        }).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            personDeleteModal: null,
            deleteConfirmationText: '',
            alsoDeleteEvents: false,
            alsoDeleteRecordings: false,
        })

        await expectLogic(logic, () => {
            logic.actions.showPersonDeleteModal(OTHER_PERSON)
        }).toMatchValues({
            deleteConfirmationText: '',
            alsoDeleteEvents: false,
            alsoDeleteRecordings: false,
        })
    })
})
