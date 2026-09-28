import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { RecordingPreview } from './RecordingPreview'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: () => ({ checkRecordingInfo: jest.fn() }),
    useValues: () => ({ getRecordingExists: () => true, isRecordingExistsLoading: () => false }),
}))

jest.mock('lib/components/ViewRecordingButton/ViewRecordingButton', () => ({
    RecordingPlayerType: { Modal: 'modal' },
    useRecordingButton: () => ({ onClick: jest.fn(), disabledReason: null }),
}))

describe('RecordingPreview', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('says the preview is unavailable and captures one event after the retry also fails', () => {
        const { container } = render(
            <RecordingPreview
                sessionId="sess-1"
                thumbnailSrc="/thumbnail"
                alt="Recording preview"
                source="scanner_finding"
            />
        )

        fireEvent.error(container.querySelector('img')!)
        expect(screen.queryByText('Preview unavailable')).not.toBeInTheDocument()

        act(() => {
            jest.runOnlyPendingTimers()
        })
        fireEvent.error(container.querySelector('img')!)

        expect(container.querySelector('img')).toBeNull()
        expect(screen.getByText('Preview unavailable')).toBeInTheDocument()
        const calls = (posthog.capture as jest.Mock).mock.calls.filter(
            ([name]) => name === 'Inbox recording preview unavailable'
        )
        expect(calls).toEqual([
            ['Inbox recording preview unavailable', { inbox_client: 'cloud', source: 'scanner_finding' }, undefined],
        ])
    })
})
