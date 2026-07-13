<!-- Hand-curated list pending §4.6 Phase 0 per-method usage data ("top ~25 by usage"); signatures are verbatim copies from the generated discovery index (src/generated/code-exec/discovery-index.json) — re-verify them whenever the SDK regenerates. This comment is stripped at import and never reaches the prompt. -->

### SDK cheat sheet

Common signatures on `client` — call these with `run` directly, no discovery round trip. For every other method, and for params/response shapes, use `types` first.

```ts
// Feature flags
featureFlags.list(params?: FeatureFlagsListParams, opts?: RequestOptions): Promise<PaginatedFeatureFlagList>
featureFlags.get(params: FeatureFlagsGetParams, opts?: RequestOptions): Promise<FeatureFlag>
featureFlags.create(params?: FeatureFlagsCreateParams, opts?: RequestOptions): Promise<FeatureFlag>
featureFlags.update(params: FeatureFlagsUpdateParams, opts?: RequestOptions): Promise<FeatureFlag>
// Queries (any insight query node; see also the typed wrappers below and the `sql` verb)
query.run<T = QueryResponse>(body: { query: QueryNode }, opts?: RequestOptions): Promise<T>
query.trends(params: QueryTrendsParams, opts?: RequestOptions): Promise<TrendsQueryResponse>
query.funnel(params: QueryFunnelParams, opts?: RequestOptions): Promise<FunnelsQueryResponse>
query.retention(params: QueryRetentionParams, opts?: RequestOptions): Promise<RetentionQueryResponse>
// Insights
insights.list(params?: InsightsListParams, opts?: RequestOptions): Promise<PaginatedInsightList>
insights.get(params: InsightsGetParams, opts?: RequestOptions): Promise<Insight>
insights.create(params?: InsightsCreateParams, opts?: RequestOptions): Promise<Insight>
insights.update(params: InsightsUpdateParams, opts?: RequestOptions): Promise<Insight>
// Dashboards
dashboards.list(params?: DashboardsListParams, opts?: RequestOptions): Promise<PaginatedDashboardBasicList>
dashboards.get(params: DashboardsGetParams, opts?: RequestOptions): Promise<Dashboard>
dashboards.create(params?: DashboardsCreateParams, opts?: RequestOptions): Promise<Dashboard>
// Persons & cohorts
persons.list(params?: PersonsListParams, opts?: RequestOptions): Promise<PaginatedPersonRecordList>
persons.get(params: PersonsGetParams, opts?: RequestOptions): Promise<PersonRecord>
cohorts.list(params?: CohortsListParams, opts?: RequestOptions): Promise<PaginatedCohortList>
cohorts.create(params?: CohortsCreateParams, opts?: RequestOptions): Promise<Cohort>
// Experiments & surveys
experiments.list(params?: ExperimentsListParams, opts?: RequestOptions): Promise<PaginatedExperimentBasicList>
experiments.create(params: ExperimentsCreateParams, opts?: RequestOptions): Promise<Experiment>
surveys.list(params?: SurveysListParams, opts?: RequestOptions): Promise<PaginatedSurveyList>
// Error tracking
queryErrorTracking.issuesList(params?: QueryErrorTrackingIssuesListParams, opts?: RequestOptions): Promise<ErrorTrackingIssuesListResponse>
errorTrackingIssues.update(params: ErrorTrackingIssuesUpdateParams, opts?: RequestOptions): Promise<ErrorTrackingIssueRead>
// Annotations & actions
annotations.create(params?: AnnotationsCreateParams, opts?: RequestOptions): Promise<Annotation>
actions.list(params?: ActionsListParams, opts?: RequestOptions): Promise<PaginatedActionList>
```

Event/property taxonomy (verifying that events and properties exist) has no SDK method yet — use `call read-data-schema` per the data-discovery section below.
