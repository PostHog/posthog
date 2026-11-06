import type { SavedHeatmapRequestApi } from 'products/web_analytics/frontend/generated/api.schemas'

export const DEFAULT_HEATMAP_NAME = 'Untitled heatmap'

export type HeatmapSettings = Required<
    Pick<SavedHeatmapRequestApi, 'url' | 'data_url' | 'type' | 'block_consent_modals'>
> & { name: string }

type HeatmapSettingsInput = Partial<
    Pick<SavedHeatmapRequestApi, 'name' | 'url' | 'data_url' | 'type' | 'block_consent_modals'>
>

export function normalizeHeatmapSettings(settings: HeatmapSettingsInput): HeatmapSettings {
    return {
        name: settings.name?.trim() || DEFAULT_HEATMAP_NAME,
        url: settings.url?.trim() || '',
        data_url: settings.data_url?.trim() || null,
        type: settings.type ?? 'screenshot',
        block_consent_modals: settings.block_consent_modals ?? false,
    }
}
