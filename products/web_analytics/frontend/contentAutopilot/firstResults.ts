import type {
    AEOPromptSetCountsApi,
    AEOPromptSetOverviewApi,
    AEOPromptSetRankingsApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

export interface ShareOfVoiceRow {
    domain: string
    name: string
    isYou: boolean
    visibility: number | null
}

export const answeredChecks = (counts: AEOPromptSetCountsApi): number => counts.checks - counts.failed

export interface FirstResultsView {
    openAnswers: number
    brandedAnswers: number
    named: number
    cited: number
    brandedCited: number
    brands: ShareOfVoiceRow[]
}

export const firstResultsView = (
    nonBranded: AEOPromptSetOverviewApi,
    branded: AEOPromptSetOverviewApi,
    rankings: AEOPromptSetRankingsApi,
    limit = 6
): FirstResultsView => {
    const openAnswers = answeredChecks(nonBranded.current)
    const rows: ShareOfVoiceRow[] = rankings.brands
        .filter((brand) => brand.answers_mentioning > 0 || brand.is_target)
        .map((brand) => ({
            domain: brand.domain,
            name: brand.name || brand.domain,
            isYou: brand.is_target,
            visibility: openAnswers > 0 ? brand.answers_mentioning / openAnswers : null,
        }))
        .sort((a, b) => (b.visibility ?? -1) - (a.visibility ?? -1))
    const top = rows.slice(0, limit)
    const you = rows.find((row) => row.isYou)
    return {
        openAnswers,
        brandedAnswers: answeredChecks(branded.current),
        named: nonBranded.current.mentioned,
        cited: nonBranded.current.cited,
        brandedCited: branded.current.cited,
        brands: you && !top.includes(you) ? [...top.slice(0, limit - 1), you] : top,
    }
}
