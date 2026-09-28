import { shouldShowHeatmapCaptureAllowlistNotice } from './HeatmapCaptureAllowlistNotice'
import { HeatmapCaptureMode } from './heatmapCaptureSettingsLogic'

describe('shouldShowHeatmapCaptureAllowlistNotice', () => {
    it.each<
        [string, { heatmapsOptIn: boolean; captureMode: HeatmapCaptureMode; enforcementEnabled: boolean }, boolean]
    >([
        [
            'enabled, allowlist mode, not yet enforced',
            { heatmapsOptIn: true, captureMode: 'url_allowlist', enforcementEnabled: false },
            true,
        ],
        ['heatmaps off', { heatmapsOptIn: false, captureMode: 'url_allowlist', enforcementEnabled: false }, false],
        ['allow-all mode', { heatmapsOptIn: true, captureMode: 'all', enforcementEnabled: false }, false],
        ['already enforced', { heatmapsOptIn: true, captureMode: 'url_allowlist', enforcementEnabled: true }, false],
    ])('%s', (_name, params, expected) => {
        expect(shouldShowHeatmapCaptureAllowlistNotice(params)).toBe(expected)
    })
})
