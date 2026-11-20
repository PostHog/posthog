import { escapeDottedHogQLIdentifier, escapeHogQLString } from 'lib/utils/hogql'

/** The Search Console table with one row per day and search, which a `GoogleSearchConsole` source syncs by default. */
const SEARCH_CONSOLE_QUERY_TABLE = 'search_analytics_by_query'

export interface KeywordSearchWindow {
    /** First and last day, YYYY-MM-DD. Search Console days are Pacific time, so the edges can be a day off. */
    from: string
    to: string
}

export interface KeywordSearchImpressions {
    /** Times the site appeared on Google for a search that contains the keyword. */
    impressions: number
    clicks: number
    /** Distinct searches that contain the keyword and showed the site. */
    searches: number
    /** Average position of the site's top result, weighted by impressions. Null with no impressions. */
    position: number | null
}

/** The table to read, or null when the project has no Search Console source. A source created with a
 * prefix has the prefix between the source name and the table, so the name is matched by its end. */
export const findSearchConsoleQueryTable = (tables: { name: string }[]): string | null => {
    const names = tables.map(({ name }) => name)
    return (
        names.find((name) => name.endsWith(`.${SEARCH_CONSOLE_QUERY_TABLE}`)) ??
        names.find((name) => name.endsWith(SEARCH_CONSOLE_QUERY_TABLE)) ??
        null
    )
}

/** One row per keyword that a web search contained, case ignored, as the keyword report matches text.
 * A search that contains two keywords counts for both. */
export const buildKeywordImpressionsQuery = (
    tableName: string,
    keywords: string[],
    { from, to }: KeywordSearchWindow
): string =>
    `SELECT
    arrayJoin(arrayFilter(keyword -> position(search, keyword) > 0, [${keywords.map((keyword) => escapeHogQLString(keyword.toLowerCase())).join(', ')}])) AS keyword,
    sum(shown) AS impressions,
    sum(clicked) AS clicks,
    uniq(search) AS searches,
    sum(rank * shown) / sum(shown) AS position
FROM (
    SELECT lower(query) AS search, toFloat(impressions) AS shown, toFloat(clicks) AS clicked, toFloat(position) AS rank
    FROM ${escapeDottedHogQLIdentifier(tableName)}
    WHERE toDate(date) >= toDate(${escapeHogQLString(from)}) AND toDate(date) <= toDate(${escapeHogQLString(to)})
        AND (search_type = 'web' OR search_type IS NULL)
)
GROUP BY keyword`

export const keywordImpressionsFromRows = (rows: unknown[][]): Record<string, KeywordSearchImpressions> =>
    Object.fromEntries(
        rows.map(([keyword, impressions, clicks, searches, position]) => [
            String(keyword),
            {
                impressions: Number(impressions ?? 0),
                clicks: Number(clicks ?? 0),
                searches: Number(searches ?? 0),
                position: position === null || position === undefined ? null : Number(position),
            },
        ])
    )
