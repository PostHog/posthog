import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReplayObservationSceneComponent } from './ReplayObservation'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

const mockRecordingRendered = jest.fn()
let observationOverrides: Record<string, unknown> = {}

jest.mock('./ObservationRecording', () => {
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
                    completed_at: '2026-07-01T00:01:00Z',
                    ...observationOverrides,
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

    afterEach(() => {
        cleanup()
        replayObservationSceneLogic.unmount()
        observationOverrides = {}
    })

    it('renders the player beside the result and seeks it from citations and shared links', async () => {
        render(<ReplayObservationSceneComponent />)
        await screen.findByText(/The next page did not open\./)
        await screen.findByTestId('observation-recording')
        expect(mockRecordingRendered).toHaveBeenLastCalledWith({
            playerKey: 'vision-observation-observation-example',
            sessionRecordingId: 'session-observation-example',
            pendingSeek: null,
        })

        fireEvent.click(screen.getByText('00:05'))
        expect(mockRecordingRendered).toHaveBeenLastCalledWith(
            expect.objectContaining({ pendingSeek: { ms: 5000, trigger: expect.any(Number) } })
        )

        // A seek belongs to one observation, so moving to a sibling drops it.
        fireEvent.keyDown(document.body, { key: 'j' })
        await waitFor(() =>
            expect(mockRecordingRendered).toHaveBeenLastCalledWith({
                playerKey: 'vision-observation-observation-next',
                sessionRecordingId: 'session-observation-next',
                pendingSeek: null,
            })
        )

        for (const seconds of [0, 5.25]) {
            act(() => router.actions.push('/replay-vision/observations/observation-shared', { t: seconds }))
            await waitFor(() =>
                expect(mockRecordingRendered).toHaveBeenLastCalledWith({
                    playerKey: 'vision-observation-observation-shared',
                    sessionRecordingId: 'session-observation-shared',
                    pendingSeek: { ms: seconds * 1000, trigger: expect.any(Number) },
                })
            )
        }

        for (const timestamp of ['-1', 'invalid']) {
            act(() => router.actions.push('/replay-vision/observations/observation-shared', { t: timestamp }))
            await waitFor(() =>
                expect(mockRecordingRendered).toHaveBeenLastCalledWith(expect.objectContaining({ pendingSeek: null }))
            )
        }
    })

    it.each([
        ['an unrated succeeded scan', {}, true, true],
        ['an already rated scan', { label: { is_correct: true, feedback: '' } }, false, true],
        [
            'a failed scan',
            { status: 'failed', error_reason: 'provider_transient:Timed out.', scanner_result: null },
            false,
            false,
        ],
    ])(
        'for %s, shows the rating question and the event link only when they apply',
        async (_name, overrides, asksForRating, linksEvent) => {
            observationOverrides = overrides
            render(<ReplayObservationSceneComponent />)
            await screen.findByTestId('observation-recording')

            expect(screen.queryByText('Did the scanner get this right?') !== null).toBe(asksForRating)
            fireEvent.click(screen.getByText('Details'))
            expect(screen.queryByText('$recording_observed') !== null).toBe(linksEvent)
        }
    )
})
