import type { ReplayVideoExportContext } from '@/api/replayVideo'

import { videoSecondsForSessionSeconds } from './videoTime'

// Half a second of pre-roll, 10 s of activity, a 90 s idle stretch the render skipped, a gap the player never marked,
// then 30 s of activity.
const CUT: ReplayVideoExportContext = {
    video_duration_s: 40.6,
    inactivity_periods: [
        { ts_from_s: 0, ts_to_s: 10, active: true, recording_ts_from_s: 0.5, recording_ts_to_s: 10.5 },
        { ts_from_s: 10, ts_to_s: 100, active: false, recording_ts_from_s: 10.54, recording_ts_to_s: 10.54 },
        { ts_from_s: 110, ts_to_s: 140, active: true, recording_ts_from_s: 10.58, recording_ts_to_s: 40.58 },
    ],
}

describe('videoSecondsForSessionSeconds', () => {
    test.each<[string, number, ReplayVideoExportContext | undefined, number]>([
        ['an active stretch runs with the session', 5, CUT, 5.5],
        ['a skipped stretch lands where playback resumed', 50, CUT, 10.54],
        ['a gap lands where the next stretch starts', 105, CUT, 10.58],
        ['a later active stretch runs behind by the cut', 125, CUT, 25.58],
        ['before the first stretch clamps to its start', -3, CUT, 0.5],
        ['after the last stretch clamps to its end', 500, CUT, 40.58],
        ['an unreadable moment never reads as NaN', Number.NaN, CUT, 0.5],
        ['without periods both clocks read the same', 25, { video_duration_s: 60 }, 25],
        ['without periods the video length bounds the moment', 90, { video_duration_s: 60 }, 60],
        ['without an export context a moment is never negative', -4, undefined, 0],
        [
            'periods from a render that never recorded video times are ignored',
            25,
            { video_duration_s: 60, inactivity_periods: [{ ts_from_s: 0, ts_to_s: 60, active: true }] },
            25,
        ],
    ])('%s', (_name, sessionSeconds, context, expected) => {
        expect(videoSecondsForSessionSeconds(sessionSeconds, context)).toBeCloseTo(expected, 6)
    })
})
