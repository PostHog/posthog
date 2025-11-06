import pytest

from asgiref.sync import sync_to_async
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer

from posthog.schema import AssistantHogQLQuery, NodeKind

from posthog.models import Team

from products.enterprise.backend.hogai.eval.scorers.sql import evaluate_sql_query
from products.enterprise.backend.hogai.graph.sql.toolkit import SQL_SCHEMA

from ..base import MaxPublicEval
from ..scorers import PlanAndQueryOutput, PlanCorrectness, QueryAndPlanAlignment, QueryKindSelection, TimeRangeRelevancy

QUERY_GENERATION_MAX_RETRIES = 3


class RetryEfficiency(Scorer):
    """Evaluate the efficiency of SQL query generation based on retry attempts. Higher scores for fewer retries."""

    def _name(self):
        return "retry_efficiency"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        retry_count = output.get("query_generation_retry_count", 0) if output else 0

        # Score is inversely proportional to retry count
        score = 1.0 if retry_count == 0 else 1 - (retry_count / QUERY_GENERATION_MAX_RETRIES)

        return Score(name=self._name(), score=score, metadata={"query_generation_retry_count": retry_count})

    def _run_eval_sync(self, output, expected=None, **kwargs):
        retry_count = output.get("query_generation_retry_count", 0) if output else 0

        # Score is inversely proportional to retry count
        score = 1.0 if retry_count == 0 else 1 - (retry_count / QUERY_GENERATION_MAX_RETRIES)

        return Score(name=self._name(), score=score, metadata={"query_generation_retry_count": retry_count})


class HogQLQuerySyntaxCorrectness(Scorer):
    def _name(self):
        return "sql_syntax_correctness"

    async def _run_eval_async(self, output: PlanAndQueryOutput, *args, **kwargs):
        return await sync_to_async(self._evaluate)(output)

    def _run_eval_sync(self, output: PlanAndQueryOutput, *args, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: PlanAndQueryOutput) -> Score:
        team = Team.objects.latest("created_at")
        if isinstance(output["query"], AssistantHogQLQuery):
            query = output["query"].query
        else:
            query = None
        return evaluate_sql_query(self._name(), query, team)


@pytest.mark.django_db
async def eval_sql(call_root_for_insight_generation, pytestconfig):
    all_cases: list[EvalCase] = [
        ### Straightforward breakdowns
        EvalCase(
            input="Count pageviews by browser, using SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to count pageviews grouped by browser:
- FROM: events table
- WHERE: event = '$pageview'
- GROUP BY: properties.$browser
- SELECT: properties.$browser, count(*) as pageview_count
- ORDER BY: pageview_count DESC
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT properties.$browser as browser, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
GROUP BY browser
ORDER BY pageview_count DESC
LIMIT 100
"""
                ),
            ),
        ),
        EvalCase(
            input="What are the top 10 countries by number of users in the last 7 days? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to find the top 10 countries by number of users in the last 7 days:
- FROM: events table
- WHERE: timestamp >= now() - interval 7 day
- GROUP BY: properties.$geoip_country_name
- SELECT: properties.$geoip_country_name, count(distinct person_id) as user_count
- ORDER BY: user_count DESC
- LIMIT: 10
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT properties.$geoip_country_name as country, count(distinct person_id) as user_count
FROM events
WHERE timestamp >= now() - interval 7 day
GROUP BY country
ORDER BY user_count DESC
LIMIT 10
"""
                ),
            ),
        ),
        ### Session duration
        EvalCase(
            input="Show me the average session duration by day of week, using SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate average session duration by day of week:
- FROM: sessions table (or equivalent calculation)
- SELECT: day_of_week(timestamp), avg(session_duration)
- GROUP BY: day_of_week
- ORDER BY: day_of_week
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT toDayOfWeek(timestamp) as day_of_week,
       avg(session.$session_duration) as avg_session_duration
FROM events
GROUP BY day_of_week
ORDER BY day_of_week
"""
                ),
            ),
        ),
        EvalCase(
            input="What percentage of users who visited the pricing page made a purchase in this month? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate the percentage of users who visited the pricing page and also made a purchase this month:
- Subquery 1: Find distinct users who visited pricing page this month
- Subquery 2: Find distinct users who made a purchase this month
- Calculate: (Users who did both) / (Users who visited pricing page) * 100
- Time filter: date_trunc('month', timestamp) = date_trunc('month', now())
""",
                query=AssistantHogQLQuery(
                    query="""
WITH pricing_visitors AS (
    SELECT distinct person_id
    FROM events
    WHERE event = 'viewed_pricing_page'
    AND date_trunc('month', timestamp) = date_trunc('month', now())
),
purchasers AS (
    SELECT distinct person_id
    FROM events
    WHERE event = 'purchase'
    AND date_trunc('month', timestamp) = date_trunc('month', now())
)
SELECT
    count(DISTINCT pv.person_id) AS pricing_visitors_count,
    count(DISTINCT p.person_id) AS purchasers_count,
    (count(DISTINCT p.person_id) * 100.0 / nullIf(count(DISTINCT pv.person_id), 0)) AS conversion_percentage
FROM pricing_visitors pv
LEFT JOIN purchasers p ON pv.person_id = p.person_id
"""
                ),
            ),
        ),
        ### Conversion
        EvalCase(
            input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) in sequence? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to count users who completed the full onboarding sequence:
- Use window functions to assign sequence numbers to each step
- Check that users have all three steps in the correct order
- Count distinct users who completed all steps
""",
                query=AssistantHogQLQuery(
                    query="""
WITH occurences AS (
    SELECT
        person_id,
        event,
        timestamp,
        ROW_NUMBER() OVER (PARTITION BY person_id, event ORDER BY timestamp) as occurrence
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_funnel AS (
    SELECT
        person_id,
        maxIf(timestamp, event = 'viewed_welcome_page') as welcome_time,
        maxIf(timestamp, event = 'created_profile') as profile_time,
        maxIf(timestamp, event = 'completed_tutorial') as tutorial_time
    FROM occurences
    WHERE occurrence = 1
    GROUP BY person_id
    HAVING count(distinct event) = 3
)
SELECT count(*) as users_completed_onboarding
FROM user_funnel
WHERE welcome_time < profile_time AND profile_time < tutorial_time
"""
                ),
            ),
        ),
        EvalCase(
            input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) regardless of sequence? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to count users who completed the full onboarding sequence:
- Aggregate occurences of each event per user
- Count users who have all three events
""",
                query=AssistantHogQLQuery(
                    query="""
WITH occurences AS (
    SELECT person_id, event
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_funnel AS (
    SELECT
        person_id,
        count(distinct event) as event_count
    FROM occurences
    GROUP BY person_id
)
SELECT count(*) as users_completed_onboarding
FROM user_funnel
WHERE event_count = 3
"""
                ),
            ),
        ),
        ### Property math
        EvalCase(
            # As of May 2025, trends insights don't support "number of distinct values of property" math, so we MUST use SQL here
            input="The number of distinct values of property $browser seen in each of the last 14 days",
            expected=PlanAndQueryOutput(
                plan="""
Query:
- Count distinct values of property $browser seen in each of the last 14 days
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT date_trunc('day', timestamp) as day, count(distinct properties.$browser) as distinct_browser_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day
"""
                ),
            ),
        ),
        EvalCase(
            input="Sum up the total amounts paid for the 'paid_bill' event over the past month for Hedgebox Inc. Make sure to use SQL.",
            expected=PlanAndQueryOutput(
                plan="Logic:\n- Filter the 'paid_bill' events for the past month.\n- Sum the 'amount_usd' property for these events.\n- Ensure the events are associated with 'Hedgebox Inc.' by filtering using the 'name' property of the 'organization' entity.\n\nSources:\n- Event: 'paid_bill'\n  - Use the 'amount_usd' property to calculate the total amount paid.\n  - Filter events to the past month.\n- Entity: 'organization'\n  - Use the 'name' property to filter for 'Hedgebox Inc.'",
                query=AssistantHogQLQuery(
                    query="""
SELECT sum(toFloat(properties.amount_usd)) AS total_amount_paid
FROM events
WHERE event = 'paid_bill'
  AND timestamp >= now() - INTERVAL 30 DAY
  AND organization.properties.name = 'Hedgebox Inc.'
"""
                ),
            ),
        ),
        ### Open questions to list persons
        EvalCase(
            input="Who are the 5 users I should interview around file download usage?",
            expected=PlanAndQueryOutput(
                plan="""
Query to find the 5 users to interview around file download usage:
- FROM: events table
- WHERE: event contains file download usage patterns or properties related to file download
- GROUP BY: person_id to get unique users
- SELECT: person.properties (name, email, etc.) and usage metrics
- ORDER BY: usage frequency or recency
- LIMIT: 5
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT
    person_id,
    person.properties.email as email,
    person.properties.name as name,
    count(*) as usage_count,
    max(timestamp) as last_used
FROM events
WHERE event = 'downloaded_file'
GROUP BY person_id, person.properties.email, person.properties.name
ORDER BY usage_count DESC, last_used DESC
LIMIT 5
"""
                ),
            ),
        ),
        EvalCase(
            input="Who are the 5 users that have downloaded the most files in the past few weeks? Who are they?",
            expected=PlanAndQueryOutput(
                plan="""
Query to find the 5 users who downloaded the most files in the past few weeks:
- FROM: events table
- WHERE: event = 'downloaded_file', timestamp in past few weeks
- GROUP BY: person_id
- SELECT: person details and count of downloads
- ORDER BY: download count DESC
- LIMIT: 5
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT
    person_id,
    person.properties.email as email,
    person.properties.name as name,
    count(*) as file_download_count,
    max(timestamp) as last_download
FROM events
WHERE event = 'downloaded_file'
    AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY person_id, person.properties.email, person.properties.name
ORDER BY file_download_count DESC
LIMIT 5
"""
                ),
            ),
        ),
        EvalCase(
            input="Show me 10 example person profiles of file download users",
            expected=PlanAndQueryOutput(
                plan="""
Query to show 10 example person profiles of file download users:
- FROM: events table joined with person data
- WHERE: events related to file download usage
- GROUP BY: person_id to get unique users
- SELECT: person profile information (properties)
- LIMIT: 10
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT DISTINCT
    person_id,
    person.properties.email as email,
    person.properties.name as name,
    person.properties.company as company,
    person.properties.role as role,
    person.properties.created_at as user_created_at,
    count(*) as file_download_event_count
FROM events
WHERE event = 'downloaded_file'
GROUP BY person_id, person.properties.email, person.properties.name,
         person.properties.company, person.properties.role, person.properties.created_at
LIMIT 10
"""
                ),
            ),
        ),
        ### Funnel trends (currently not an insight type supported by Max, should fall back to SQL)
        EvalCase(
            input="What's the conversion rate from trial signup to paid subscription by cohort month?",
            expected=PlanAndQueryOutput(
                plan="""
Logic:
- **Layer 1 (Feature Usage Calculation)**: For each user, count occurrences of each event type (uploads, downloads, shares, invites, upgrades, downgrades) within their first 30 days of activity using `countIf()` aggregation. Also calculate total event count with `count()` and find first activity date with `MIN(timestamp)`.
- **Layer 2 (Churn Status Determination)**: For each user, determine if they had any activity between days 31-90 after their first activity using window function `MIN(timestamp) OVER (PARTITION BY person_id)` to establish baseline, then `MAX(activity_31_90)` aggregation to check for any activity in the churn observation period.
- **Layer 3 (User Metrics Join)**: Join feature usage data with churn status on person_id to create complete user profiles with both feature usage and churn outcome.
- **Layer 4 (Feature Analysis)**: For each feature type, calculate correlation metrics using `AVG()` for churn rates, `CASE WHEN` conditional aggregation for segmented averages, and `corr()` for correlation coefficients between feature usage and churn.
- **Layer 5 (Results Union)**: Combine results for all features using `UNION ALL` and sort by absolute correlation coefficient using `ORDER BY ABS(correlation_coefficient) DESC`.

Sources:
- events table (primary analysis)
    - Used to count feature usage events in first 30 days per user
    - Filtered with `WHERE timestamp >= now() - INTERVAL 120 DAY` for performance
    - Grouped by person_id with `HAVING first_activity_date <= now() - INTERVAL 90 DAY` to ensure complete observation window
- events table (churn determination)
    - Used to detect activity patterns in days 31-90 after first activity
    - Same timestamp filter applied for consistency
    - Window function applied to establish per-user activity timeline
    - Grouped by person_id to determine final churn status

Query kind:
- **Cohort Analysis with Feature Correlation**: Chosen over simple churn analysis because it provides predictive insights by correlating specific feature usage patterns with retention outcomes. UNION ALL structure allows systematic comparison across multiple features while maintaining identical time windows and churn definitions. CTE approach chosen over subqueries for performance optimization since the same complex user metrics calculation is needed for all features.

Tradeoffs:
- **Time Window Rigidity**: Fixed 30-day feature observation and 60-day churn observation periods may miss users with different engagement patterns, but provides consistent comparison framework.
- **Binary Churn Definition**: Treats any activity in days 31-90 as "retained" regardless of engagement depth, which may miss nuanced retention patterns but simplifies correlation analysis.
- **Historical Data Limitation**: Requires 90+ days of historical data per user, limiting analysis to older cohorts and excluding recent signups from correlation insights.
- **Feature Usage Counting**: Simple event counting doesn't account for usage intensity or quality (e.g., file size for uploads), but enables straightforward correlation calculation across diverse feature types.
- **Memory vs Computation**: CTE approach trades memory usage for computational efficiency by materializing user metrics once rather than recalculating for each feature analysis.
""",
                query=AssistantHogQLQuery(
                    query="""
WITH trial_signups AS (
    SELECT
        person_id,
        date_trunc('month', min(timestamp)) as cohort_month
    FROM events
    WHERE event = 'trial_signup'
    GROUP BY person_id
),
conversions AS (
    SELECT DISTINCT person_id
    FROM events
    WHERE event = 'subscription_started'
)
SELECT
    cohort_month,
    count(DISTINCT t.person_id) as trial_signups,
    count(DISTINCT c.person_id) as paid_conversions,
    (count(DISTINCT c.person_id) * 100.0 / count(DISTINCT t.person_id)) as conversion_rate
FROM trial_signups t
LEFT JOIN conversions c ON t.person_id = c.person_id
GROUP BY cohort_month
ORDER BY cohort_month
"""
                ),
            ),
        ),
        EvalCase(
            input="Show me the median time between page views for each browser type, excluding users with only 1 page view",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate median time between page views by browser type:
- Filter to pageview events only
- Use window functions to calculate time differences between consecutive pageviews per user
- Group by browser type (from event properties)
- Calculate median using quantile functions
- Exclude users with only 1 pageview
""",
                query=AssistantHogQLQuery(
                    query="""
WITH pageview_times AS (
    SELECT
        person_id,
        properties.$browser as browser_type,
        timestamp,
        LAG(timestamp) OVER (PARTITION BY person_id ORDER BY timestamp) as prev_timestamp
    FROM events
    WHERE event = '$pageview'
),
time_diffs AS (
    SELECT
        person_id,
        browser_type,
        dateDiff('second', prev_timestamp, timestamp) as seconds_between_views
    FROM pageview_times
    WHERE prev_timestamp IS NOT NULL
),
user_pageview_counts AS (
    SELECT person_id, count(*) as pageview_count
    FROM events
    WHERE event = '$pageview'
    GROUP BY person_id
    HAVING pageview_count > 1
)

SELECT
    'uploads' AS feature,
    AVG(CASE WHEN churned = 1 THEN uploads_30d ELSE 0 END) AS avg_usage_churned,
    AVG(CASE WHEN churned = 0 THEN uploads_30d ELSE 0 END) AS avg_usage_retained,
    AVG(churned) AS overall_churn_rate,
    AVG(CASE WHEN uploads_30d > 0 THEN churned ELSE NULL END) AS churn_rate_with_feature,
    AVG(CASE WHEN uploads_30d = 0 THEN churned ELSE NULL END) AS churn_rate_without_feature,
    corr(toFloat(uploads_30d), toFloat(churned)) AS correlation_coefficient
FROM user_metrics

UNION ALL

SELECT
    'downloads' AS feature,
    AVG(CASE WHEN churned = 1 THEN downloads_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN downloads_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN downloads_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN downloads_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(downloads_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'shares' AS feature,
    AVG(CASE WHEN churned = 1 THEN shares_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN shares_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN shares_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN shares_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(shares_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'invites' AS feature,
    AVG(CASE WHEN churned = 1 THEN invites_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN invites_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN invites_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN invites_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(invites_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'upgrades' AS feature,
    AVG(CASE WHEN churned = 1 THEN upgrades_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN upgrades_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN upgrades_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN upgrades_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(upgrades_30d), toFloat(churned))
FROM user_metrics

ORDER BY ABS(corr(toFloat(uploads_30d), toFloat(churned))) DESC
"""
                ),
            ),
        ),
        ### Correlation
        EvalCase(
            input=(
                "Which features are most predictive of churn? Show correlation between feature usage in first 30 days and churn in next 60 days",
                "Use events uploaded_file, downloaded_file, shared_file_link, invited_team_member, upgraded_plan, downgraded_plan. Use lack of activity as the churn signal. Analyze the last 120 days of data.",
            ),
            expected=PlanAndQueryOutput(
                plan="""
Query to analyze feature usage correlation with churn:
- Define user cohorts based on signup date
- Track feature usage in first 30 days after signup
- Identify churn status in days 31-90 after signup
- Calculate correlation between each feature usage and churn
- Use statistical functions to measure predictive power
""",
                query=AssistantHogQLQuery(
                    query="""
WITH user_metrics AS (
    SELECT
        fu.person_id,
        fu.uploads_30d,
        fu.downloads_30d,
        fu.shares_30d,
        fu.invites_30d,
        fu.upgrades_30d,
        fu.downgrades_30d,
        fu.total_events_30d,
        cs.churned
    FROM (
        -- Feature usage in first 30 days
        SELECT
            e.person_id,
            countIf(e.event = 'uploaded_file') AS uploads_30d,
            countIf(e.event = 'downloaded_file') AS downloads_30d,
            countIf(e.event = 'shared_file_link') AS shares_30d,
            countIf(e.event = 'invited_team_member') AS invites_30d,
            countIf(e.event = 'upgraded_plan') AS upgrades_30d,
            countIf(e.event = 'downgraded_plan') AS downgrades_30d,
            count() AS total_events_30d,
            MIN(e.timestamp) AS first_activity_date
        FROM events e
        WHERE e.timestamp >= now() - INTERVAL 120 DAY
        GROUP BY e.person_id
        HAVING first_activity_date <= now() - INTERVAL 90 DAY
    ) fu
    INNER JOIN (
        -- Churn status (no activity in days 31-90)
        SELECT
            person_id,
            MIN(timestamp) AS first_activity_date,
            CASE
                WHEN MAX(activity_31_90) = 1 THEN 0 ELSE 1
            END AS churned
        FROM (
            SELECT
                person_id,
                timestamp,
                CASE WHEN timestamp >= min_timestamp + INTERVAL 30 DAY AND timestamp < min_timestamp + INTERVAL 90 DAY THEN 1 ELSE 0 END AS activity_31_90,
                min_timestamp
            FROM (
                SELECT
                    person_id,
                    timestamp,
                    MIN(timestamp) OVER (PARTITION BY person_id) AS min_timestamp
                FROM events
                WHERE timestamp >= now() - INTERVAL 120 DAY
            )
        )
        GROUP BY person_id, min_timestamp
        HAVING min_timestamp <= now() - INTERVAL 90 DAY
    ) cs ON fu.person_id = cs.person_id
)

SELECT
    'uploads' AS feature,
    AVG(CASE WHEN churned = 1 THEN uploads_30d ELSE 0 END) AS avg_usage_churned,
    AVG(CASE WHEN churned = 0 THEN uploads_30d ELSE 0 END) AS avg_usage_retained,
    AVG(churned) AS overall_churn_rate,
    AVG(CASE WHEN uploads_30d > 0 THEN churned ELSE NULL END) AS churn_rate_with_feature,
    AVG(CASE WHEN uploads_30d = 0 THEN churned ELSE NULL END) AS churn_rate_without_feature,
    corr(toFloat(uploads_30d), toFloat(churned)) AS correlation_coefficient
FROM user_metrics

UNION ALL

SELECT
    'downloads' AS feature,
    AVG(CASE WHEN churned = 1 THEN downloads_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN downloads_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN downloads_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN downloads_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(downloads_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'shares' AS feature,
    AVG(CASE WHEN churned = 1 THEN shares_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN shares_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN shares_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN shares_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(shares_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'invites' AS feature,
    AVG(CASE WHEN churned = 1 THEN invites_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN invites_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN invites_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN invites_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(invites_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'upgrades' AS feature,
    AVG(CASE WHEN churned = 1 THEN upgrades_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN upgrades_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN upgrades_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN upgrades_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(upgrades_30d), toFloat(churned))
FROM user_metrics

ORDER BY ABS(corr(toFloat(uploads_30d), toFloat(churned))) DESC
"""
                ),
            ),
        ),
        EvalCase(
            input="Show weekly pageview counts with Monday as the start of week for the last 4 weeks. Use SQL.",
            expected=PlanAndQueryOutput(
                plan="Logic:\n- Query pageview events\n- Group by week starting on Monday using toStartOfWeek with mode 1\n- Filter to last 4 weeks\n- Count pageviews per week\n\nSources:\n- events table\n  - event = '$pageview'\n  - timestamp for date grouping and filtering",
                query=AssistantHogQLQuery(
                    query="""
SELECT toStartOfWeek(timestamp, 1) as week_start, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 4 WEEK
GROUP BY week_start
ORDER BY week_start
"""
                ),
            ),
        ),
        EvalCase(
            input="Get the earliest session date for each user in the last month. Use SQL.",
            expected=PlanAndQueryOutput(
                plan="Logic:\n- Query events from last month\n- Find minimum timestamp per user\n- Convert DateTime to Date using toDate\n- Group by person_id\n\nSources:\n- events table\n  - person_id for grouping\n  - timestamp for finding minimum and date conversion",
                query=AssistantHogQLQuery(
                    query="""
SELECT person_id, toDate(min(timestamp)) as first_session_date
FROM events
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY person_id
ORDER BY first_session_date
"""
                ),
            ),
        ),
        EvalCase(
            input="I want to split a comma-separated interests property and count unique users. Use SQL.",
            expected=PlanAndQueryOutput(
                plan="Logic:\n- Query events table for users with interests property\n- Split comma-separated values using splitByChar\n- Handle nullable fields with coalesce\n- Count distinct person_id\n\nSources:\n- events table\n  - properties.interests (comma-separated string)\n  - person_id for counting unique users",
                query=AssistantHogQLQuery(
                    query="""
SELECT count(distinct person_id) as users_with_interests
FROM events
WHERE properties.interests IS NOT NULL
  AND length(splitByChar(',', coalesce(properties.interests, ''))) > 0
"""
                ),
            ),
        ),
    ]

    await MaxPublicEval(
        experiment_name="sql",
        task=call_root_for_insight_generation,
        scores=[
            QueryKindSelection(expected=NodeKind.HOG_QL_QUERY),
            PlanCorrectness(
                query_kind=NodeKind.HOG_QL_QUERY,
                evaluation_criteria="""
1. A plan must define a clear intent for the SQL query to be generated, including which tables/entities are being queried, what filters are being applied, and what is being returned.
2. Compare tables, entities, filters, aggregations, group by clauses, and any other SQL elements mentioned in the 'expected plan' and 'output plan'.
3. Check if the outlined query in 'output plan' can answer the user's question according to the 'expected plan'.
4. If 'expected plan' mentions specific joins, aggregations, or window functions, check if 'output plan' includes similar operations, and heavily penalize if they are not present or significantly different.
5. If 'expected plan' mentions specific time range filters, check if 'output plan' includes similar time range filters, and heavily penalize if they are not present or different.
6. Heavily penalize if the 'output plan' contains any excessive operations not present in the 'expected plan' that would change the meaning of the query.
""",
            ),
            QueryAndPlanAlignment(
                query_kind=NodeKind.HOG_QL_QUERY,
                json_schema=SQL_SCHEMA,
                evaluation_criteria="""
Most importantly, evaluate the `query` field, containing the generated HogQL.
HogQL is simply an SQL flavor derived from ClickHouse SQL, with some PostHog-specific syntax.
The most important piece of PostHog-specific syntax is easy access to JSON properties, which is done using `.`, like so: `SELECT properties.$browser FROM events`.
It's also possible to access nested tables, such the `events` table has a `person` field that actually points to the related row in the `persons` table (the concrete field on `events` is `person_id`).
This means the following syntax is valid and useful too: `SELECT person.properties.foo.bar FROM events`.
The other standard table is `sessions`, which contains data of the session the event belongs to (though events can be outside of a session as well).

Important points:
- The generated query should use `person_id` or `person.id` for any aggregation on unique users, should NOT be using `distinct_id` or properties.
- $identify generally should not be used, as they're mostly for internal purposes, and not useful for insights. A more useful event (or no event filter) should be used.
- For session duration, `session.$session_duration` should be used instead of things like `properties.$session_duration`.""",
            ),
            HogQLQuerySyntaxCorrectness(),
            TimeRangeRelevancy(query_kind=NodeKind.HOG_QL_QUERY),
            RetryEfficiency(),
        ],
        data=all_cases,
        pytestconfig=pytestconfig,
    )
