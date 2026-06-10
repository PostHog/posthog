import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DropZone } from './DropZone'

const OVERLAY_TEXT = 'Drop files to attach'

function fileDataTransfer(files: File[] = []): { files: File[]; types: string[] } {
    return { files, types: ['Files'] }
}

function textDataTransfer(): { files: File[]; types: string[] } {
    return { files: [], types: ['text/plain'] }
}

function renderDropZone(): { zone: HTMLElement; onDropFiles: jest.Mock } {
    const onDropFiles = jest.fn()
    const { container } = render(
        <DropZone onDropFiles={onDropFiles}>
            <div data-attr="child">
                <textarea className="LemonTextArea" data-attr="editor" />
                <button data-attr="nested-button">Send</button>
            </div>
        </DropZone>
    )
    const zone = container.querySelector('[data-attr="task-drop-zone"]') as HTMLElement
    expect(zone).not.toBeNull()
    return { zone, onDropFiles }
}

describe('DropZone', () => {
    afterEach(cleanup)

    it('renders children without the overlay by default', () => {
        renderDropZone()
        expect(screen.getByTestId('child')).toBeInTheDocument()
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })

    it('shows the overlay on dragenter with files', () => {
        const { zone } = renderDropZone()
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer() })
        expect(screen.getByText(OVERLAY_TEXT)).toBeInTheDocument()
    })

    it('does not show the overlay for non-file drags', () => {
        const { zone } = renderDropZone()
        fireEvent.dragEnter(zone, { dataTransfer: textDataTransfer() })
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })

    it('keeps the overlay visible while dragging across nested children', () => {
        const { zone } = renderDropZone()
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer() })
        fireEvent.dragEnter(screen.getByTestId('nested-button'), { dataTransfer: fileDataTransfer() })
        fireEvent.dragLeave(screen.getByTestId('nested-button'), { dataTransfer: fileDataTransfer() })
        expect(screen.getByText(OVERLAY_TEXT)).toBeInTheDocument()
    })

    it('hides the overlay once dragenter and dragleave are balanced', () => {
        const { zone } = renderDropZone()
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer() })
        fireEvent.dragEnter(screen.getByTestId('nested-button'), { dataTransfer: fileDataTransfer() })
        fireEvent.dragLeave(screen.getByTestId('nested-button'), { dataTransfer: fileDataTransfer() })
        fireEvent.dragLeave(zone, { dataTransfer: fileDataTransfer() })
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })

    it('calls onDropFiles with the dropped files and hides the overlay', () => {
        const { zone, onDropFiles } = renderDropZone()
        const file = new File(['hello'], 'hello.txt', { type: 'text/plain' })
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer([file]) })
        fireEvent.drop(zone, { dataTransfer: fileDataTransfer([file]) })
        expect(onDropFiles).toHaveBeenCalledTimes(1)
        expect(onDropFiles).toHaveBeenCalledWith([file])
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })

    it('ignores drops with no files but still hides the overlay', () => {
        const { zone, onDropFiles } = renderDropZone()
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer() })
        fireEvent.drop(zone, { dataTransfer: fileDataTransfer() })
        expect(onDropFiles).not.toHaveBeenCalled()
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })

    it('does not process drops targeting the LemonTextArea editor', () => {
        const { zone, onDropFiles } = renderDropZone()
        const file = new File(['hello'], 'hello.txt', { type: 'text/plain' })
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer([file]) })
        fireEvent.drop(screen.getByTestId('editor'), { dataTransfer: fileDataTransfer([file]) })
        expect(onDropFiles).not.toHaveBeenCalled()
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })

    it('prevents default browser behavior on dragover and drop', () => {
        const { zone } = renderDropZone()
        const dragOverResult = fireEvent.dragOver(zone, { dataTransfer: fileDataTransfer() })
        const dropResult = fireEvent.drop(zone, { dataTransfer: fileDataTransfer() })
        expect(dragOverResult).toBe(false)
        expect(dropResult).toBe(false)
    })

    it('renders the overlay with pointer-events disabled so it cannot intercept clicks', () => {
        const { zone } = renderDropZone()
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer() })
        const overlay = zone.querySelector('[data-attr="task-drop-zone-overlay"]') as HTMLElement
        expect(overlay).not.toBeNull()
        expect(overlay).toHaveClass('pointer-events-none')
    })

    it('handles dragleave without a prior dragenter without showing the overlay later', () => {
        const { zone } = renderDropZone()
        fireEvent.dragLeave(zone, { dataTransfer: fileDataTransfer() })
        fireEvent.dragEnter(zone, { dataTransfer: fileDataTransfer() })
        expect(screen.getByText(OVERLAY_TEXT)).toBeInTheDocument()
        fireEvent.dragLeave(zone, { dataTransfer: fileDataTransfer() })
        expect(screen.queryByText(OVERLAY_TEXT)).toBeNull()
    })
})
