import type { HeatmapCaptureSettingsApi } from '../../generated/api.schemas'
import { shouldShowHeatmapsPricingNotice } from './HeatmapsPricingNotice'

const settings = (overrides: Partial<HeatmapCaptureSettingsApi>): HeatmapCaptureSettingsApi => ({
    capture_mode: 'url_allowlist',
    url_allowlist: [],
    enforcement_enabled: false,
    can_capture_all_urls: false,
    capture_url_limit: 3,
    ...overrides,
})

describe('shouldShowHeatmapsPricingNotice', () => {
    it.each<[string, HeatmapCaptureSettingsApi | null, boolean]>([
        ['free plan, not yet enforced', settings({}), true],
        ['settings not loaded', null, false],
        ['plan captures all URLs', settings({ can_capture_all_urls: true, capture_url_limit: null }), false],
        ['already enforced', settings({ enforcement_enabled: true }), false],
    ])('%s', (_name, captureSettings, expected) => {
        expect(shouldShowHeatmapsPricingNotice(captureSettings)).toBe(expected)
    })
})
