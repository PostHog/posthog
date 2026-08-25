import { ObservationVersionMarkerApi } from '../generated/api.schemas'
import { ScanDroughtScannerFields, scanDrought } from './scanDrought'

const NOW = new Date('2026-01-10T12:00:00Z')

function scanner(overrides: Partial<ScanDroughtScannerFields> = {}): ScanDroughtScannerFields {
    return {
        enabled: true,
        limit_reached: false,
        scanner_version: 3,
        sampling_rate: 1,
        updated_at: '2026-01-08T12:00:00Z',
        last_swept_at: '2026-01-10T11:00:00Z',
        ...overrides,
    }
}

function marker(version: number): ObservationVersionMarkerApi {
    return {
        date: '2026-01-05',
        version,
        prompt: 'Did the user struggle?',
        scanner_config: { prompt: 'Did the user struggle?' },
        scanner_type: 'monitor',
        model: 'gemini-3.7-flash',
        provider: 'google',
        emits_signals: false,
        query: null,
        sampling_rate: 1,
        sampling_mode: 'comprehensive',
        up: 0,
        down: 0,
        total: 5,
    }
}

describe('scanDrought', () => {
    it('fires when the current version has no observations despite sweeps since the change', () => {
        expect(scanDrought(scanner(), [marker(1), marker(2)], NOW)).toEqual({
            everScanned: true,
            samplingRate: 1,
        })
    })

    it('reports a scanner that never scanned anything as everScanned false', () => {
        expect(scanDrought(scanner({ scanner_version: 1 }), [], NOW)).toEqual({
            everScanned: false,
            samplingRate: 1,
        })
    })

    it('passes through the sampling rate for the copy', () => {
        expect(scanDrought(scanner({ sampling_rate: 0.1 }), [], NOW)).toEqual({
            everScanned: false,
            samplingRate: 0.1,
        })
    })

    it.each([
        ['stats not loaded yet', scanner(), null],
        ['scanner disabled', scanner({ enabled: false }), []],
        ['credit limit reached explains the silence', scanner({ limit_reached: true }), []],
        ['sampling rate 0 means paused on purpose', scanner({ sampling_rate: 0 }), []],
        ['current version already has observations', scanner(), [marker(3)]],
        [
            'config changed less than a day ago',
            scanner({ updated_at: '2026-01-10T00:00:00Z', last_swept_at: '2026-01-10T11:00:00Z' }),
            [],
        ],
        [
            'no sweep has covered sessions ending after the change',
            scanner({ last_swept_at: '2026-01-08T11:00:00Z' }),
            [],
        ],
    ])('stays silent when %s', (_label, fields, markers) => {
        expect(scanDrought(fields, markers, NOW)).toBeNull()
    })
})
