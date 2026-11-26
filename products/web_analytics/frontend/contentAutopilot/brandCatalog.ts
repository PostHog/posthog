import { ApiError } from 'lib/api-error'

import { aeoBrandsCreate, aeoBrandsList, aeoBrandsPartialUpdate } from 'products/web_analytics/frontend/generated/api'
import type { BrandKindEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

export const bareDomain = (value: string): string =>
    value
        .trim()
        .toLowerCase()
        .replace(/^[a-z]+:\/\//, '')
        .replace(/^www\./, '')
        .split(/[/?#]/)[0]

export const looksLikeDomain = (value: string): boolean => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(bareDomain(value))

export const saveBrand = async (
    teamId: string,
    domain: string,
    kind: Extract<BrandKindEnumApi, 'own' | 'competitor'>,
    name?: string
): Promise<void> => {
    const bare = bareDomain(domain)
    try {
        await aeoBrandsCreate(teamId, { domain: bare, kind, ...(name ? { name } : {}) })
    } catch (error) {
        // A domain the runs already cited is in the catalog, so it is relabeled instead of added twice.
        if (!(error instanceof ApiError) || error.status !== 400) {
            throw error
        }
        const matches = await aeoBrandsList(teamId, { search: bare, limit: 20 })
        const existing = matches.results.find((brand) => brand.domain === bare)
        if (!existing) {
            throw error
        }
        await aeoBrandsPartialUpdate(teamId, existing.id, { kind, status: 'confirmed' })
    }
}
