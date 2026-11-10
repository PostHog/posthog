import { lastDeletedBucket } from './lastDeletedBucket'

describe('lastDeletedBucket', () => {
    it.each([
        ['keeps the day the deletion starts from', ['2025-11-29', '2025-11-30', '2025-12-01', '2025-12-02'], 1],
        ['includes a week that is only partly deleted', ['2025-11-20', '2025-11-27', '2025-12-04'], 1],
        ['includes the last hour before the cutoff', ['2025-11-30 23:00:00', '2025-12-01 00:00:00'], 0],
        ['finds nothing when the range starts after the cutoff', ['2025-12-01', '2025-12-02'], null],
    ])('%s', (_name, dates, expected) => {
        expect(lastDeletedBucket(dates, '2025-12-01')).toEqual(expected)
    })
})
