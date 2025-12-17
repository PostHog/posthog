/*
Pageview Counts - Page views by LLM Analytics page type

Counts $pageview events on LLM Analytics pages, categorized by page type.
URL patterns are mapped to page types via config.pageview_mappings.
More specific patterns should be listed before general ones in config.

Produces metrics: pageviews_dashboard, pageviews_traces, pageviews_generations, etc.

Example: Pageview to /project/1/llm-analytics/traces → pageviews_traces metric
*/

SELECT
    date(timestamp) as date,
    team_id,
    concat('pageviews_', page_type) as metric_name,
    toFloat64(count(*)) as metric_value
FROM (
    SELECT
        timestamp,
        team_id,
        CASE
            {% for url_path, metric_suffix in pageview_mappings %}
            WHEN JSONExtractString(properties, '$current_url') LIKE '%{{ url_path }}%' THEN '{{ metric_suffix }}'
            {% endfor %}
            ELSE NULL
        END as page_type
    FROM llma_pageview_events
)
WHERE page_type IS NOT NULL
GROUP BY date, team_id, page_type
