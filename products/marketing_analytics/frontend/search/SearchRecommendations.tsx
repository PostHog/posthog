import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonSelect } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { MarketingAnalyticsSearchRow } from '~/queries/schema/schema-general'

import { SEARCH_PERFORMANCE_QUERY_KEY, SEARCH_PLATFORM_LABELS } from './searchPerformance'
import { searchPerformanceTableLogic, SearchPerformanceTableLogicProps } from './searchPerformanceTableLogic'
import { searchRecommendationsLogic } from './searchRecommendationsLogic'

export function SearchRecommendations({
    query,
    queryKey,
    onSelect,
}: SearchPerformanceTableLogicProps & { onSelect?: (row: MarketingAnalyticsSearchRow) => void }): JSX.Element | null {
    const logic = searchPerformanceTableLogic({ query, queryKey })
    const {
        recommendationsEnabled,
        recommendationGoalId,
        recommendationSource,
        goals,
        conversionsEnabled,
        conversionsLoading,
        conversionsError,
        conversionsResponse,
        responseLoading,
        responseError,
        searchResponse,
        queryId,
        rows,
    } = useValues(logic)
    const { setRecommendationSource } = useActions(logic)

    const ready =
        recommendationsEnabled &&
        queryKey === SEARCH_PERFORMANCE_QUERY_KEY &&
        !!searchResponse &&
        !responseLoading &&
        !responseError &&
        !(
            conversionsEnabled &&
            recommendationSource !== 'platform' &&
            (!recommendationGoalId ||
                conversionsLoading ||
                conversionsError ||
                !conversionsResponse ||
                conversionsResponse.posthogConversionsWarning)
        )
    const { currentTeamId } = useValues(teamLogic)
    const recommendationLogic = searchRecommendationsLogic({
        teamId: currentTeamId,
        query,
        goalId: recommendationGoalId,
        enabled: !!ready,
        refreshKey: queryId,
    })
    const { result, resultLoading } = useValues(recommendationLogic)
    const { loadRecommendations } = useActions(recommendationLogic)
    const recommendations = result?.recommendations ?? []

    if (
        !recommendationsEnabled ||
        queryKey !== SEARCH_PERFORMANCE_QUERY_KEY ||
        responseLoading ||
        responseError ||
        !searchResponse
    ) {
        return null
    }

    return (
        <LemonCard className="my-3" aria-label="Search recommendations">
            <div className="flex flex-wrap gap-2 items-center justify-between mb-2">
                <h3 className="mb-0">Suggestions to investigate</h3>
                <LemonSelect
                    aria-label="Conversions for suggestions"
                    value={
                        conversionsEnabled && recommendationSource !== 'platform'
                            ? (recommendationGoalId ?? 'posthog')
                            : 'platform'
                    }
                    onChange={setRecommendationSource}
                    options={[
                        ...(conversionsEnabled && !recommendationGoalId
                            ? [{ value: 'posthog', label: 'Select a PostHog goal' }]
                            : []),
                        ...(conversionsEnabled
                            ? goals.map((goal) => ({ value: goal.id, label: `PostHog: ${goal.name}` }))
                            : []),
                        { value: 'platform', label: 'Ad platform conversions' },
                    ]}
                />
            </div>
            <p className="text-secondary text-sm">
                These checks compare the rows in this report with the comparison period. They do not measure
                profitability or statistical significance. Recent conversions may still arrive. No campaign changes are
                applied.
            </p>
            {conversionsEnabled &&
            recommendationSource !== 'platform' &&
            (conversionsLoading ||
                conversionsError ||
                !conversionsResponse ||
                conversionsResponse.posthogConversionsWarning ||
                !recommendationGoalId) ? (
                <p className="mb-0">
                    Suggestions using PostHog conversions need complete conversion data and a configured goal. You can
                    also select ad platform conversions.
                </p>
            ) : !query.compareFilter?.compare ? (
                <p className="mb-0">Turn on period comparison to check for changes in search performance.</p>
            ) : resultLoading ? (
                <p className="mb-0">Checking search performance…</p>
            ) : result?.warning ? (
                <div className="flex flex-wrap items-center gap-2">
                    <p className="mb-0">{result.warning}</p>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => loadRecommendations()}
                        loading={resultLoading}
                    >
                        Try again
                    </LemonButton>
                </div>
            ) : recommendations.length === 0 ? (
                <p className="mb-0">
                    No suggestions with enough comparable data. This does not mean performance is optimal.
                </p>
            ) : (
                <ul className="list-none p-0 mb-0 divide-y">
                    {recommendations.map(({ row, kind, current, previous }) => {
                        const original = rows.find(
                            (candidate) =>
                                candidate.platform === row.platform &&
                                (candidate.keyword ?? null) === (row.keyword ?? null) &&
                                (candidate.page ?? null) === (row.page ?? null) &&
                                (candidate.matchType ?? null) === (row.matchType ?? null) &&
                                (candidate.currency ?? null) === (row.currency ?? null)
                        )
                        return (
                            <li
                                key={JSON.stringify([
                                    row.keyword,
                                    row.page,
                                    row.platform,
                                    row.matchType,
                                    row.currency,
                                    kind,
                                ])}
                                className="py-3"
                            >
                                <div className="flex flex-wrap justify-between items-center gap-2">
                                    <strong className="break-all">{row.page ?? row.keyword ?? 'Unknown term'}</strong>
                                    {onSelect && original && (
                                        <LemonButton size="small" type="secondary" onClick={() => onSelect(original)}>
                                            Explore
                                        </LemonButton>
                                    )}
                                </div>
                                <span className="text-secondary text-xs">{SEARCH_PLATFORM_LABELS[row.platform]}</span>
                                <p className="my-1">
                                    {kind === 'spend_without_conversions'
                                        ? `${row.cost?.toFixed(2)} ${row.currency} spent across ${row.clicks} clicks with no conversions, compared with ${previous} conversions in the comparison period. Review attribution, conversion delay, and the landing page.`
                                        : kind === 'higher_cpa'
                                          ? `Cost per conversion rose from ${previous.toFixed(2)} to ${current.toFixed(2)} ${row.currency}. Both periods have at least 10 conversions. Review what changed before adjusting spend.`
                                          : `Organic CTR fell from ${(previous * 100).toFixed(1)}% to ${(current * 100).toFixed(1)}%. Both periods have at least 1,000 impressions. Review position and traffic changes.`}
                                </p>
                                <span className="text-secondary text-xs">
                                    {kind === 'lower_organic_ctr'
                                        ? 'Source: Google Search Console. This check does not use conversions.'
                                        : `Conversions: ${recommendationGoalId ? `PostHog, ${goals.find((goal) => goal.id === recommendationGoalId)?.name}` : 'ad platform'}.`}
                                </span>
                            </li>
                        )
                    })}
                </ul>
            )}
        </LemonCard>
    )
}
