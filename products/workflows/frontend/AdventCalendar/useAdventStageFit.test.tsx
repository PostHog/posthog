import { render } from '@testing-library/react'

import { ADVENT_DOOR_SIZE } from './adventGraph'
import { AdventStageFit, useAdventStageFit } from './useAdventStageFit'

function Stage({ onFit }: { onFit: (fit: AdventStageFit) => void }): JSX.Element {
    const fit = useAdventStageFit()
    onFit(fit)
    return <div ref={fit.ref} />
}

describe('useAdventStageFit', () => {
    let measure: jest.SpyInstance

    afterEach(() => {
        measure.mockRestore()
    })

    it.each([
        ['a phone', 390, 700, { door: 58, pictureWidth: 1244, scrollsSideways: true }],
        ['a narrow desktop scene', 520, 700, { door: 24, pictureWidth: 520, scrollsSideways: false }],
        ['a desktop scene', 1200, 720, { door: 56, pictureWidth: 1200, scrollsSideways: false }],
    ])('fits the picture to a stage on %s', (_, width, height, expected) => {
        measure = jest
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockReturnValue({ width, height } as DOMRect)
        let fit: AdventStageFit | null = null

        render(<Stage onFit={(next) => (fit = next)} />)

        expect({
            door: Math.round(ADVENT_DOOR_SIZE * fit!.zoom),
            pictureWidth: Math.round(fit!.box.width),
            scrollsSideways: fit!.scrollsSideways,
        }).toEqual(expected)
    })
})
