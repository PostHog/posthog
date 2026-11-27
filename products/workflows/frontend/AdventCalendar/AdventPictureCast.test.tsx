import { fireEvent, render } from '@testing-library/react'

import { drawAdventRewards } from './adventDraw'
import { buildAdventGraph } from './adventGraph'
import { AdventPictureCast } from './AdventPictureCast'

const GRAPH = buildAdventGraph(
    { opened: [1, 2, 3], answers: { 2: 'tim' } },
    4,
    drawAdventRewards('0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01')
)

describe('AdventPictureCast', () => {
    it.each([
        ['while no door is revealing', false, ['door-1']],
        ['while another door is revealing', true, []],
    ])('selects a hog clicked %s', (_, isRevealing, activated) => {
        const onActivateDoor = jest.fn()
        const revealing = GRAPH.doors.find((door) => door.id === 'door-3-lower')!
        const { container } = render(
            <AdventPictureCast
                graph={GRAPH}
                reveal={isRevealing ? { door: revealing, phase: 'shown', zoom: 1 } : null}
                onActivateDoor={onActivateDoor}
            />
        )

        const hog = container.querySelector<HTMLButtonElement>('[data-attr="advent-hog-1"]')!
        fireEvent.click(hog)

        expect(onActivateDoor.mock.calls.map(([doorId]) => doorId)).toEqual(activated)
        expect(hog.disabled).toBe(isRevealing)
    })

    it('keeps a landed hog in place while another door reveals, so it does not land again', () => {
        const revealing = GRAPH.doors.find((door) => door.id === 'door-3-lower')!
        const cast = (isRevealing: boolean): JSX.Element => (
            <AdventPictureCast
                graph={GRAPH}
                reveal={isRevealing ? { door: revealing, phase: 'shown', zoom: 1 } : null}
                onActivateDoor={jest.fn()}
            />
        )
        const { container, rerender } = render(cast(false))
        const hog = container.querySelector('[data-attr="advent-hog-1"]')
        expect(hog).not.toBeNull()

        rerender(cast(true))
        expect(container.querySelector('[data-attr="advent-hog-1"]')).toBe(hog)

        rerender(cast(false))
        expect(container.querySelector('[data-attr="advent-hog-1"]')).toBe(hog)
    })
})
