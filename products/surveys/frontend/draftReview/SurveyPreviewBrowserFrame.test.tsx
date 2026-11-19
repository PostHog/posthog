import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SurveyPreviewBrowserFrame } from './SurveyPreviewBrowserFrame'

let mockFrameSize = { width: 1000, height: 800 }
let mockSnapshot: { imageUrl: string; pageUrl: string; viewportWidth: number } | null = null

jest.mock('lib/hooks/useResizeObserver', () => ({ useResizeObserver: () => mockFrameSize }))
jest.mock('scenes/surveys/surveyLogic', () => ({
    surveyLogic: { mockValues: { survey: { id: 'survey-1', conditions: null, appearance: { position: 'right' } } } },
}))
jest.mock('./surveySiteSnapshotLogic', () => ({
    surveySiteSnapshotLogic: () => ({ mockValues: { readySnapshot: mockSnapshot } }),
}))
jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: (logic: any) => logic.mockValues }))

const frame = (): JSX.Element => (
    <SurveyPreviewBrowserFrame device="desktop" highlightedArea={null} preview={<div data-attr="survey" />} />
)

function loadPage(naturalWidth: number, naturalHeight: number): void {
    const image = document.querySelector('img') as HTMLImageElement
    Object.defineProperty(image, 'naturalWidth', { value: naturalWidth, configurable: true })
    Object.defineProperty(image, 'naturalHeight', { value: naturalHeight, configurable: true })
    fireEvent.load(image)
}

function zoomButtons(): { zoomOut: HTMLElement; toggle: HTMLElement; zoomIn: HTMLElement } {
    const [zoomOut, toggle, zoomIn] = Array.from(
        document.querySelectorAll<HTMLElement>('[data-attr="survey-draft-review-preview-zoom"] button')
    )
    return { zoomOut, toggle, zoomIn }
}

describe('SurveyPreviewBrowserFrame zoom', () => {
    beforeEach(() => {
        mockFrameSize = { width: 1000, height: 800 }
        mockSnapshot = { imageUrl: 'https://example.com/page.png', pageUrl: 'https://example.com', viewportWidth: 2000 }
    })
    afterEach(cleanup)

    it.each([
        ['loads', (): void => {}],
        ['fails to load', (): void => void fireEvent.error(document.querySelector('img') as HTMLImageElement)],
    ])('keeps the survey visible while the page image %s', (_, imageEvent) => {
        render(frame())
        imageEvent()

        expect(screen.getByTestId('survey').closest('.invisible')).toBeNull()
    })

    it('follows fit when the frame grows past a zoom', () => {
        const { rerender } = render(frame())
        loadPage(4000, 2000)
        fireEvent.click(zoomButtons().zoomIn)
        mockFrameSize = { width: 1600, height: 1600 }
        rerender(frame())

        expect(zoomButtons().toggle).toHaveTextContent('80%')
        expect(zoomButtons().zoomOut).toHaveAttribute('aria-disabled', 'true')
    })

    it('starts a new snapshot at its own fit', () => {
        const { rerender } = render(frame())
        loadPage(4000, 2000)
        fireEvent.click(zoomButtons().zoomIn)
        mockSnapshot = { imageUrl: 'https://example.com/other.png', pageUrl: 'https://example.com', viewportWidth: 500 }
        rerender(frame())
        loadPage(1000, 1000)

        expect(zoomButtons().toggle).toHaveTextContent('100%')
    })

    it('returns to fit after zooming in and out', () => {
        mockFrameSize = { width: 405, height: 800 }
        render(frame())
        loadPage(4000, 2000)
        fireEvent.click(zoomButtons().zoomIn)
        fireEvent.click(zoomButtons().zoomOut)

        expect(zoomButtons().zoomOut).toHaveAttribute('aria-disabled', 'true')
    })

    it('applies every pinch event that lands before a render', () => {
        render(frame())
        loadPage(4000, 2000)
        const viewport = (document.querySelector('img') as HTMLElement).parentElement!.parentElement!.parentElement!
        act(() => {
            for (const _ of [0, 1]) {
                viewport.dispatchEvent(new WheelEvent('wheel', { deltaY: -25, ctrlKey: true, cancelable: true }))
            }
        })

        expect(zoomButtons().toggle).toHaveTextContent(`${Math.round(50 * Math.exp(0.5))}%`)
    })
})
