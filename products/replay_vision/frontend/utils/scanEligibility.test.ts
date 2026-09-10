import { SessionRecordingType } from '~/types'

import { recordingScanBlock } from './scanEligibility'

describe('recordingScanBlock', () => {
    const recording = (partial: Partial<SessionRecordingType>): SessionRecordingType =>
        ({ id: 'session-1', recording_duration: 300, active_seconds: 120, ...partial }) as SessionRecordingType

    it('clears a recording the gate accepts', () => {
        expect(recordingScanBlock(recording({}))).toBeNull()
    })

    it('has nothing to say without metadata', () => {
        expect(recordingScanBlock(null)).toBeNull()
        expect(recordingScanBlock(recording({ recording_duration: undefined, active_seconds: undefined }))).toBeNull()
    })

    it.each([
        ['too_long', { recording_duration: 10800, active_seconds: 4200 }],
        ['too_short', { recording_duration: 8, active_seconds: 8 }],
        ['too_inactive', { recording_duration: 600, active_seconds: 4 }],
    ])('blocks %s recordings with the numbers behind it', (kind, metadata) => {
        const block = recordingScanBlock(recording(metadata))
        expect(block?.kind).toEqual(kind)
        expect(block?.reason).toContain('Replay vision')
    })

    it('holds off on the minimums while a recording is still going', () => {
        expect(recordingScanBlock(recording({ recording_duration: 8, active_seconds: 4, ongoing: true }))).toBeNull()
        // Active time only grows, so the maximum still applies.
        expect(recordingScanBlock(recording({ active_seconds: 4200, ongoing: true }))?.kind).toEqual('too_long')
    })
})
