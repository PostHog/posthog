import { dayjs } from 'lib/dayjs'

import { couldRecordingBeExpired } from './recordingRetention'

describe('couldRecordingBeExpired', () => {
    it('rules out observations younger than the shortest retention period and keeps older ones as candidates', () => {
        expect(couldRecordingBeExpired(dayjs().subtract(29, 'day').toISOString())).toBe(false)
        expect(couldRecordingBeExpired(dayjs().subtract(31, 'day').toISOString())).toBe(true)
    })
})
