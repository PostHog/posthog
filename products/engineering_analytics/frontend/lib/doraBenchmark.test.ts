import {
    changeFailureBenchmark,
    deploymentFrequencyBenchmark,
    leadTimeBenchmark,
    restoreTimeBenchmark,
} from './doraBenchmark'

describe('doraBenchmark', () => {
    it.each([
        [null, null],
        [0, null],
        [1, 'elite'],
        [0.9, 'high'],
        [1 / 7, 'high'],
        [0.1, 'medium'],
        [1 / 30, 'medium'],
        [0.01, 'low'],
    ])('deploymentFrequencyBenchmark(%p) is %p', (perDay, band) => {
        expect(deploymentFrequencyBenchmark(perDay)?.band ?? null).toBe(band)
    })

    it.each([
        [null, null],
        [3600, 'elite'],
        [86400, 'high'],
        [7 * 86400, 'medium'],
        [30 * 86400, 'low'],
    ])('leadTimeBenchmark(%p) is %p', (seconds, band) => {
        expect(leadTimeBenchmark(seconds)?.band ?? null).toBe(band)
    })

    it.each([
        [null, null],
        [0, 'elite'],
        [0.05, 'elite'],
        [0.1, 'high'],
        [0.15, 'medium'],
        [0.2, 'low'],
    ])('changeFailureBenchmark(%p) is %p', (share, band) => {
        expect(changeFailureBenchmark(share)?.band ?? null).toBe(band)
    })

    it.each([
        [null, null],
        [1800, 'elite'],
        [3600, 'high'],
        [86400, 'medium'],
        [7 * 86400, 'low'],
    ])('restoreTimeBenchmark(%p) is %p', (seconds, band) => {
        expect(restoreTimeBenchmark(seconds)?.band ?? null).toBe(band)
    })
})
