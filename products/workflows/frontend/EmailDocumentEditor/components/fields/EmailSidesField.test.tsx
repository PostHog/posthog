import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { EmailSides } from '../../emailDocument'
import { EmailSidesField } from './EmailSidesField'

const EVEN = { top: 12, right: 12, bottom: 12, left: 12 }
const UNEVEN = { top: 1, right: 2, bottom: 3, left: 4 }

describe('EmailSidesField', () => {
    let saved: EmailSides | undefined

    afterEach(cleanup)

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

    it('keeps the four sides open when editing makes them equal', () => {
        render(<Field start={{ ...EVEN, right: 2 }} />)
        fireEvent.change(screen.getByLabelText('Padding Right'), { target: { value: '12' } })
        expect(saved).toEqual(EVEN)
        expect(screen.getByLabelText('Padding Right')).toBeTruthy()
    })

    it.each([
        ['same sides from uneven', UNEVEN, ['Same on all sides'], [{ top: 1, right: 1, bottom: 1, left: 1 }]],
        ['same sides when they are already equal', EVEN, ['Set each side', 'Same on all sides'], []],
        ['each side', EVEN, ['Set each side'], []],
    ])('switching to %s writes only what it must', (_, start, clicks, writes) => {
        const onChange = jest.fn()
        function Switched(): JSX.Element {
            const [value, setValue] = useState<EmailSides | undefined>(start)
            return (
                <EmailSidesField
                    label="Padding"
                    value={value}
                    placeholder={EVEN}
                    onChange={(next) => {
                        onChange(next)
                        setValue(next)
                    }}
                />
            )
        }
        render(<Switched />)
        clicks.forEach((name) => fireEvent.click(screen.getByLabelText(name)))
        expect(onChange.mock.calls.map(([next]) => next)).toEqual(writes)
        expect(!!screen.queryByLabelText('Padding Top')).toBe(clicks[clicks.length - 1] === 'Set each side')
    })

    it('does not keep four sides open after clicking the already selected each side', () => {
        const field = (value: EmailSides): JSX.Element => (
            <EmailSidesField label="Padding" value={value} placeholder={EVEN} onChange={() => {}} />
        )
        const { rerender } = render(field(UNEVEN))
        fireEvent.click(screen.getByLabelText('Set each side'))
        rerender(field(EVEN))
        expect(screen.queryByLabelText('Padding Top')).toBeNull()
    })

    it('names the selected mode for screen readers', () => {
        render(<Field start={EVEN} />)
        fireEvent.click(screen.getByLabelText('Set each side'))
        expect(screen.getByLabelText('Padding: Set each side')).toBeTruthy()
        fireEvent.click(screen.getByLabelText('Same on all sides'))
        expect(screen.getByLabelText('Padding: Same on all sides')).toBeTruthy()
    })
})
