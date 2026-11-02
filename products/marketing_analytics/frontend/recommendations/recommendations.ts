import { marketingSourceName } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import {
    MarketingAnalyticsRecommendation,
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationsSource,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

export const RECOMMENDATIONS_QUERY_KEY = 'marketing-recommendations'

export const RECOMMENDATION_RULE_LABELS: Record<MarketingAnalyticsRecommendationRule, string> = {
    budget_constrained: 'Limited by budget',
    brand_leak: 'Brand searches',
    scale_campaign: 'Room to grow',
    review_campaign: 'High cost per conversion',
    policy_limited: 'Ads limited by policy',
    brand_overlap: 'Brand overlap',
    content_gap: 'Content gap',
    keyword_gap: 'Keyword gap',
    spend_without_conversions: 'Spend without conversions',
    striking_distance: 'Striking distance',
}

export const RECOMMENDATION_RULE_DESCRIPTIONS: Record<MarketingAnalyticsRecommendationRule, string> = {
    budget_constrained: 'Google Ads limits these campaigns by budget and suggests a higher daily budget.',
    brand_leak: 'Campaigns that are not about your brand spend on searches for your brand name.',
    scale_campaign: 'Conversions cost less than your average, but the campaign loses impressions to budget or ad rank.',
    review_campaign: 'Conversions cost much more than your average across campaigns that are not about your brand.',
    policy_limited: 'Google limits some ads in these campaigns for policy reasons, so they show less often.',
    brand_overlap: 'You pay for brand searches where your site already ranks in the top 3 organically.',
    content_gap: 'Searches that convert cheaply in ads, where your site ranks below position 10 or not at all.',
    keyword_gap: 'Popular organic searches you do not bid on, made of words that already convert in your ads.',
    spend_without_conversions:
        'Search terms that cost at least twice your average cost per conversion and never converted.',
    striking_distance: 'Searches where your site ranks between positions 5 and 20. The top 3 gets most of the clicks.',
}

export type RecommendationCategory = 'waste' | 'grow' | 'organic' | 'fix'

const RULE_CATEGORIES: Record<MarketingAnalyticsRecommendationRule, RecommendationCategory> = {
    spend_without_conversions: 'waste',
    brand_leak: 'waste',
    review_campaign: 'waste',
    brand_overlap: 'waste',
    budget_constrained: 'grow',
    scale_campaign: 'grow',
    keyword_gap: 'grow',
    content_gap: 'organic',
    striking_distance: 'organic',
    policy_limited: 'fix',
}

export const RECOMMENDATION_CATEGORY_LABELS: Record<RecommendationCategory, string> = {
    waste: 'Cut wasted spend',
    grow: 'Grow',
    organic: 'Improve organic search',
    fix: 'Fix issues',
}

export interface RecommendationSection {
    category: RecommendationCategory
    groups: RecommendationGroup[]
}

export function sectionRecommendations(groups: RecommendationGroup[]): RecommendationSection[] {
    return (Object.keys(RECOMMENDATION_CATEGORY_LABELS) as RecommendationCategory[])
        .map((category) => ({ category, groups: groups.filter((group) => RULE_CATEGORIES[group.rule] === category) }))
        .filter((section) => section.groups.length > 0)
}

export const IMPACT_DIRECTION_LABELS: Record<MarketingAnalyticsRecommendation['impactDirection'], string> = {
    save: 'Save',
    gain: 'Gain',
    invest: 'Invest',
    keep: 'Keep',
}

export const IMPACT_DIRECTION_DESCRIPTIONS: Record<MarketingAnalyticsRecommendation['impactDirection'], string> = {
    save: 'Spend you can cut each month',
    gain: 'Value you can add each month, from more conversions or organic clicks',
    invest: 'Extra spend these recommendations suggest each month, at most',
    keep: 'Spend these recommendations advise you to keep each month',
}

const DIRECTION_ORDER: MarketingAnalyticsRecommendation['impactDirection'][] = ['save', 'gain', 'invest', 'keep']

export interface RecommendationTotal {
    direction: MarketingAnalyticsRecommendation['impactDirection']
    currency: string | null
    amount: number
}

export interface RecommendationGroup {
    rule: MarketingAnalyticsRecommendationRule
    level: MarketingAnalyticsRecommendation['level']
    recommendations: MarketingAnalyticsRecommendation[]
    totals: RecommendationTotal[]
}

// Accounts can use different currencies, so amounts only add up within one currency.
export function sumImpact(recommendations: MarketingAnalyticsRecommendation[]): RecommendationTotal[] {
    const totals = new Map<string, RecommendationTotal>()
    for (const recommendation of recommendations) {
        if (recommendation.impact == null) {
            continue
        }
        const currency = recommendation.currency ?? null
        const key = `${recommendation.impactDirection}|${currency}`
        const total = totals.get(key) ?? { direction: recommendation.impactDirection, currency, amount: 0 }
        total.amount += recommendation.impact
        totals.set(key, total)
    }
    return [...totals.values()].sort(
        (a, b) => DIRECTION_ORDER.indexOf(a.direction) - DIRECTION_ORDER.indexOf(b.direction)
    )
}

export function groupRecommendations(recommendations: MarketingAnalyticsRecommendation[]): RecommendationGroup[] {
    const byRule = new Map<MarketingAnalyticsRecommendationRule, MarketingAnalyticsRecommendation[]>()
    for (const recommendation of recommendations) {
        byRule.set(recommendation.rule, [...(byRule.get(recommendation.rule) ?? []), recommendation])
    }
    const groups = [...byRule.entries()].map(([rule, rows]) => ({
        rule,
        level: rows[0].level,
        recommendations: rows,
        totals: sumImpact(rows),
    }))
    // The backend already orders rules by impact. Groups that only say "keep" need no action, so they go last.
    const needsAction = (group: RecommendationGroup): boolean =>
        group.recommendations.some((row) => row.impactDirection !== 'keep')
    return [...groups.filter(needsAction), ...groups.filter((group) => !needsAction(group))]
}

function syncedTable(source: ExternalDataSource, name: string): string | undefined {
    const schema = source.schemas.find((schema) => schema.name === name)
    if (!schema?.should_sync || !schema.table) {
        return undefined
    }
    return schema.table.hogql_name ?? schema.table.name
}

export interface RecommendationDataGap {
    sourceId: string
    sourceName: string
    table: string
    description: string
    rules: MarketingAnalyticsRecommendationRule[]
}

const DATA_GAP_TABLES: Omit<RecommendationDataGap, 'sourceId' | 'sourceName'>[] = [
    {
        table: 'search_term_stats',
        description: 'Turn on the search terms table to get recommendations about the searches that trigger your ads.',
        rules: [
            'brand_leak',
            'brand_overlap',
            'content_gap',
            'keyword_gap',
            'spend_without_conversions',
            'striking_distance',
        ],
    },
    {
        table: 'search_term_keyword_stats',
        description:
            'Turn on the search term keywords table to see which keyword matched each search term that wastes spend.',
        rules: ['spend_without_conversions'],
    },
    {
        table: 'campaign_impression_share_stats',
        description: 'Turn on the campaign impression share table to tell budget limits from ad rank limits.',
        rules: ['budget_constrained', 'scale_campaign'],
    },
]

// Tables a Google Ads source could turn on to get more or better recommendations. A table that is on but has
// not synced yet, or that the source does not list, gives the person nothing to do, so it is left out.
export function recommendationDataGaps(source: ExternalDataSource): RecommendationDataGap[] {
    if (source.source_type !== 'GoogleAds' || !recommendationsSource(source)) {
        return []
    }
    return DATA_GAP_TABLES.filter((gap) => {
        const schema = source.schemas.find((schema) => schema.name === gap.table)
        return !!schema && !schema.should_sync
    }).map((gap) => ({
        ...gap,
        sourceId: source.id,
        sourceName: marketingSourceName(source),
    }))
}

export function recommendationsSource(source: ExternalDataSource): MarketingAnalyticsRecommendationsSource | null {
    if (source.source_type === 'GoogleAds') {
        const campaignTable = syncedTable(source, 'campaign')
        const campaignStatsTable = syncedTable(source, 'campaign_stats')
        if (!campaignTable || !campaignStatsTable) {
            return null
        }
        return {
            sourceType: 'GoogleAds',
            campaignTable,
            campaignStatsTable,
            campaignImpressionShareTable: syncedTable(source, 'campaign_impression_share_stats'),
            customerTable: syncedTable(source, 'customer'),
            searchTermTable: syncedTable(source, 'search_term_stats'),
            searchTermKeywordTable: syncedTable(source, 'search_term_keyword_stats'),
            performanceMaxSearchTermTable: syncedTable(source, 'performance_max_search_term_stats'),
        }
    }
    if (source.source_type === 'GoogleSearchConsole') {
        const queryTable =
            syncedTable(source, 'search_analytics_by_query') ?? syncedTable(source, 'search_analytics_by_query_page')
        if (!queryTable) {
            return null
        }
        return { sourceType: 'GoogleSearchConsole', queryTable, sitesTable: syncedTable(source, 'sites') }
    }
    return null
}
