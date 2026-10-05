import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { personDeleteModalLogic } from '../logics/personDeleteModalLogic'
import { PersonDeleteModal } from './PersonDeleteModal'

const PERSON: PersonType = { id: '1', distinct_ids: ['abc'], properties: {} }

describe('PersonDeleteModal', () => {
    afterEach(cleanup)

    it('sends one request when the delete button is activated twice', async () => {
        let finishDelete = (): void => {}
        const deleteRequest = jest.spyOn(api, 'delete').mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishDelete = () => resolve(null)
                })
        )

        initKeaTests()
        const logic = personDeleteModalLogic()
        logic.mount()
        render(<PersonDeleteModal />)

        act(() => {
            logic.actions.showPersonDeleteModal(PERSON)
        })
        fireEvent.change(screen.getByPlaceholderText('delete'), { target: { value: 'delete' } })

        const deleteButton = (): HTMLElement => screen.getByText('Delete person').closest('button') as HTMLElement

        await act(async () => {
            fireEvent.click(deleteButton())
        })
        // LemonButton remounts behind a tooltip once disabledReason is set, so the node has to be read again.
        expect(deleteButton()).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(deleteButton())

        expect(deleteRequest).toHaveBeenCalledTimes(1)

        await act(async () => {
            finishDelete()
        })
    })
})
