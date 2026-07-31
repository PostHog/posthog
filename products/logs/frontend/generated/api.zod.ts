/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    ExplainRequestApi,
    LogsAlertConfigurationApi,
    LogsAlertCreateDestinationApi,
    LogsAlertDeleteDestinationApi,
    LogsAlertSimulateRequestApi,
    LogsMetricRuleApi,
    LogsRetentionRuleApi,
    LogsRetentionRuleReorderApi,
    LogsSamplingRuleApi,
    LogsSamplingRuleReorderApi,
    LogsViewApi,
    PatchedLogsAlertConfigurationApi,
    PatchedLogsMetricRuleApi,
    PatchedLogsRetentionRuleApi,
    PatchedLogsSamplingRuleApi,
    PatchedLogsViewApi,
    _LogsCountRangesRequestApi,
    _LogsCountRequestApi,
    _LogsFacetValuesRequestApi,
    _LogsGroupByRequestApi,
    _LogsPatternsDiffRequestApi,
    _LogsPatternsRequestApi,
    _LogsQueryRequestApi,
    _LogsServicesRequestApi,
    _LogsSparklineRequestApi,
} from './api.zod.schemas'

export const LogsAlertsCreateBody = LogsAlertConfigurationApi

export const LogsAlertsUpdateBody = LogsAlertConfigurationApi

export const LogsAlertsPartialUpdateBody = PatchedLogsAlertConfigurationApi

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind (firing, resolved, ...) atomically.
 */
export const LogsAlertsDestinationsCreateBody = LogsAlertCreateDestinationApi

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */
export const LogsAlertsDestinationsDeleteCreateBody = LogsAlertDeleteDestinationApi

/**
 * Simulate a logs alert on historical data using the full state machine. Read-only — no alert check records are created.
 */
export const LogsAlertsSimulateCreateBody = LogsAlertSimulateRequestApi

export const LogsCountCreateBody = _LogsCountRequestApi

export const LogsCountRangesCreateBody = _LogsCountRangesRequestApi

/**
 * Explain a log entry using AI.
 *
 * POST /api/environments/:id/logs/explainLogWithAI/
 */
export const LogsExplainLogWithAICreateBody = ExplainRequestApi

export const LogsFacetValuesCreateBody = _LogsFacetValuesRequestApi

export const LogsGroupByCreateBody = _LogsGroupByRequestApi

export const LogsMetricRulesCreateBody = LogsMetricRuleApi

export const LogsMetricRulesUpdateBody = LogsMetricRuleApi

export const LogsMetricRulesPartialUpdateBody = PatchedLogsMetricRuleApi

export const LogsPatternsCreateBody = _LogsPatternsRequestApi

export const LogsPatternsDiffCreateBody = _LogsPatternsDiffRequestApi

export const LogsQueryCreateBody = _LogsQueryRequestApi

export const LogsRetentionRulesCreateBody = LogsRetentionRuleApi

export const LogsRetentionRulesUpdateBody = LogsRetentionRuleApi

export const LogsRetentionRulesPartialUpdateBody = PatchedLogsRetentionRuleApi

/**
 * Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).
 */
export const LogsRetentionRulesReorderCreateBody = LogsRetentionRuleReorderApi

export const LogsSamplingRulesCreateBody = LogsSamplingRuleApi

export const LogsSamplingRulesUpdateBody = LogsSamplingRuleApi

export const LogsSamplingRulesPartialUpdateBody = PatchedLogsSamplingRuleApi

/**
 * Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).
 */
export const LogsSamplingRulesReorderCreateBody = LogsSamplingRuleReorderApi

export const LogsServicesCreateBody = _LogsServicesRequestApi

export const LogsSparklineCreateBody = _LogsSparklineRequestApi

export const LogsViewsCreateBody = LogsViewApi

export const LogsViewsUpdateBody = LogsViewApi

export const LogsViewsPartialUpdateBody = PatchedLogsViewApi
