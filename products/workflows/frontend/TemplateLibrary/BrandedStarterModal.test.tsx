import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BrandedStarterModal } from './BrandedStarterModal'

describe('branded starter logo controls', () => {
    beforeEach(() => {
        useMocks({})
        initKeaTests()
    })

    afterEach(cleanup)

    it('offers a focusable logo picker', () => {
        render(<BrandedStarterModal id="new" />)
        const choose = screen.getByRole('button', { name: 'Choose a logo' })
        choose.focus()
        expect(choose).toHaveFocus()

        const onOpen = jest.fn()
        screen.getByRole('dialog').querySelector('input[type="file"]')!.addEventListener('click', onOpen)
        fireEvent.click(choose)
        expect(onOpen).toHaveBeenCalledTimes(1)
    })

    it('lets a user remove a selected logo without losing their other inputs', () => {
        render(<BrandedStarterModal id="new" />)
        fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'Juniper Studio' } })
        const color = screen.getByLabelText('Primary color')
        fireEvent.change(color, { target: { value: '#ffd400' } })
        fireEvent.change(screen.getByRole('dialog').querySelector<HTMLInputElement>('input[type="file"]')!, {
            target: { files: [new File(['logo'], 'logo.png', { type: 'image/png' })] },
        })
        expect(screen.getByText('logo.png')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Remove logo' }))

        expect(screen.queryByText('logo.png')).not.toBeInTheDocument()
        expect(screen.getByLabelText('Brand name')).toHaveValue('Juniper Studio')
        expect(color).toHaveValue('#ffd400')
    })
})
