import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { EmailSides } from '../../emailDocument'
import { EmailSidesField } from './EmailSidesField'

const EVEN = { top: 12, right: 12, bottom: 12, left: 12 }
const UNEVEN = { top: 1, right: 2, bottom: 3, left: 4 }

describe('EmailSidesField', () => {
    let saved: EmailSides | undefined

    function Field({ start }: { start: EmailSides }): JSX.Element {
        const [value, setValue] = useState<EmailSides | undefined>(start)
        saved = value
        return <EmailSidesField label="Padding" value={value} placeholder={EVEN} onChange={setValue} />
    }

    it.each([
        [
            'one value',
            EVEN,
            'Padding',
            { top: 0, right: 0, bottom: 0, left: 0 },
            { top: 7, right: 7, bottom: 7, left: 7 },
        ],
        ['one side', UNEVEN, 'Padding Right', { ...UNEVEN, right: 0 }, { ...UNEVEN, right: 7 }],
    ])('clearing %s saves 0, stays in its mode and takes a new number', (_, start, label, cleared, retyped) => {
        render(<Field start={start} />)
        const input = screen.getByLabelText<HTMLInputElement>(label)

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        expect(saved).toEqual(cleared)
        expect(screen.getByLabelText(label)).toBe(input)
        expect(input.value).toBe('')

        fireEvent.change(input, { target: { value: '7' } })
        expect(saved).toEqual(retyped)
        expect(input.value).toBe('7')
    })
})
