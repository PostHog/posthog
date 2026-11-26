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
        // The API stores the registrable domain, so docs.example.com can clash with example.com. Each candidate
        // contains the last two labels, and the longest domain that the input ends with is the one that clashed.
        const matches = await aeoBrandsList(teamId, { search: bare.split('.').slice(-2).join('.'), limit: 100 })
        const existing = matches.results
            .filter((brand) => bare === brand.domain || bare.endsWith(`.${brand.domain}`))
            .sort((a, b) => b.domain.length - a.domain.length)[0]
        if (!existing) {
            throw error
        }
        await aeoBrandsPartialUpdate(teamId, existing.id, { kind, status: 'confirmed' })
    }
}
