import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReplayObservationSceneComponent } from './ReplayObservation'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

const mockRecordingImported = jest.fn()
const mockRecordingRendered = jest.fn()

jest.mock('./ObservationRecording', () => {
    mockRecordingImported()
    return {
        __esModule: true,
        default: (props: unknown) => {
            mockRecordingRendered(props)
            return <div data-attr="observation-recording" />
        },
    }
})

jest.mock('./ObservationPinnedProperties', () => ({ ObservationPinnedProperties: () => null }))

jest.mock('../components/CitedMarkdown', () => {
    const { TimestampCitation } = jest.requireActual('../components/TimestampCitation')
    return {
        CitedMarkdown: ({ text, onSeek }: { text: string; onSeek: (ms: number) => void }) => (
            <>
                <span>{text}</span>
                <TimestampCitation timestampMs={5000} onSeek={onSeek} />
            </>
        ),
    }
})

describe('ReplayObservation', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/observations/:id/': ({ params }) => ({
                    id: params.id,
                    scanner_id: 'scanner-example',
                    scanner_origin: 'configured',
                    session_id: `session-${params.id}`,
                    status: 'succeeded',
                    error_reason: '',
                    scanner_snapshot: {
                        name: 'Example scanner',
                        scanner_type: 'monitor',
                        scanner_config: { prompt: 'Find navigation failures.' },
                    },
                    scanner_result: {
                        model_output: {
                            verdict: 'yes',
                            confidence: 0.9,
                            reasoning: 'The next page did not open.',
                            reasoning_segments: [
                                { kind: 'text', value: 'The next page did not open.' },
                                { kind: 'chip', timestamp_ms: 5000 },
                            ],
                        },
                    },
                    triggered_by: 'schedule',
                    created_at: '2026-07-01T00:00:00Z',
                    previous_observation_id: null,
                    next_observation_id: 'observation-next',
                    label: null,
                }),
            },
            post: {
                '/api/projects/:team/vision/observations/:id/viewed/': () => [204],
            },
        })
        initKeaTests()
        replayObservationSceneLogic.mount()
        router.actions.push('/replay-vision/observations/observation-example')
    })

    afterEach(() => replayObservationSceneLogic.unmount())

    it('shows the result before importing the player and preserves citation and collapse behavior', async () => {
        render(<ReplayObservationSceneComponent />)
        await screen.findByText(/The next page did not open\./)
        expect(mockRecordingImported).not.toHaveBeenCalled()
        expect(screen.queryByTestId('observation-recording')).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('00:05'))
        await screen.findByTestId('observation-recording')
        expect(mockRecordingImported).toHaveBeenCalledTimes(1)
        expect(mockRecordingRendered).toHaveBeenLastCalledWith({
            playerKey: 'vision-observation-observation-example',
            sessionRecordingId: 'session-observation-example',
            pendingSeek: { ms: 5000, trigger: expect.any(Number) },
        })
        expect(screen.getByText(/The next page did not open\./)).toBeInTheDocument()

        fireEvent.click(screen.getByText('Recording'))
        expect(screen.queryByTestId('observation-recording')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('Watch the recording'))
        await screen.findByTestId('observation-recording')
        expect(mockRecordingImported).toHaveBeenCalledTimes(1)
        expect(mockRecordingRendered).toHaveBeenLastCalledWith(expect.objectContaining({ pendingSeek: null }))

        fireEvent.click(screen.getByText('Next'))
        await waitFor(() =>
            expect(mockRecordingRendered).toHaveBeenLastCalledWith({
                playerKey: 'vision-observation-observation-next',
                sessionRecordingId: 'session-observation-next',
                pendingSeek: null,
            })
        )
    })
})
