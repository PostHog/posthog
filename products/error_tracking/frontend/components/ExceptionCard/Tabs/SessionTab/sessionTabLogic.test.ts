import { resolvePlaybackPosition } from './sessionTabLogic'

describe('resolvePlaybackPosition', () => {
    const bounds = { start: 1000, end: 5000 }

    it.each([
        ['inside the recording', 2000, bounds, { timestamp: 2000, outsideEdge: null }],
        ['on the start boundary', 1000, bounds, { timestamp: 1000, outsideEdge: null }],
        ['on the end boundary', 5000, bounds, { timestamp: 5000, outsideEdge: null }],
        ['before the recording', 400, bounds, { timestamp: 1000, outsideEdge: 'start' }],
        ['after the recording', 9000, bounds, { timestamp: 5000, outsideEdge: 'end' }],
        ['with no bounds yet', 9000, null, { timestamp: 9000, outsideEdge: null }],
        ['with no requested time', null, bounds, { timestamp: null, outsideEdge: null }],
    ])('resolves a position %s', (_, timestamp, recordingBounds, expected) => {
        expect(resolvePlaybackPosition(timestamp, recordingBounds)).toEqual(expected)
    })
})
