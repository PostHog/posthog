import { isLowVolumeForecast, LOW_VOLUME_OBSERVATIONS_PER_DAY } from './ScannerQuotaForecast'

const perMonthAt = (perDay: number): number => perDay * 30

describe('isLowVolumeForecast', () => {
    it.each([
        // Guards the day-rate math and the floor the editor warns below.
        ['null projection', null, false],
        ['undefined projection', undefined, false],
        ['zero projection', 0, true],
        ['just below the floor', perMonthAt(LOW_VOLUME_OBSERVATIONS_PER_DAY) - 1, true],
        ['at the floor', perMonthAt(LOW_VOLUME_OBSERVATIONS_PER_DAY), false],
        ['well above the floor', perMonthAt(30), false],
    ])('%s', (_name, perMonth, expected) => {
        expect(isLowVolumeForecast(perMonth)).toBe(expected)
    })
})
