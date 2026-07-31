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
    ErrorTrackingAssignmentRuleCreateRequestApi,
    ErrorTrackingAssignmentRuleUpdateRequestApi,
    ErrorTrackingBypassRuleCreateRequestApi,
    ErrorTrackingBypassRuleUpdateRequestApi,
    ErrorTrackingExternalReferenceResultApi,
    ErrorTrackingGroupingRuleCreateRequestApi,
    ErrorTrackingGroupingRuleUpdateRequestApi,
    ErrorTrackingIssueEventsQueryRequestApi,
    ErrorTrackingIssueMergeRequestApi,
    ErrorTrackingIssueQueryRequestApi,
    ErrorTrackingIssueReadApi,
    ErrorTrackingIssueSplitRequestApi,
    ErrorTrackingIssueWriteApi,
    ErrorTrackingIssuesListQueryRequestApi,
    ErrorTrackingReleaseCreateRequestApi,
    ErrorTrackingReleaseUpdateRequestApi,
    ErrorTrackingStackFrameBatchGetRequestApi,
    ErrorTrackingSuppressionRuleCreateRequestApi,
    ErrorTrackingSuppressionRuleUpdateRequestApi,
    ErrorTrackingSymbolSetBulkDeleteApi,
    ErrorTrackingSymbolSetBulkFinishUploadApi,
    ErrorTrackingSymbolSetBulkStartUploadApi,
    ErrorTrackingSymbolSetFinishUploadApi,
    PatchedErrorTrackingAssignmentRuleApi,
    PatchedErrorTrackingAssignmentRuleUpdateRequestApi,
    PatchedErrorTrackingBypassRuleApi,
    PatchedErrorTrackingBypassRuleUpdateRequestApi,
    PatchedErrorTrackingGroupingRuleApi,
    PatchedErrorTrackingGroupingRuleUpdateRequestApi,
    PatchedErrorTrackingIssueReadApi,
    PatchedErrorTrackingIssueWriteApi,
    PatchedErrorTrackingReleaseUpdateRequestApi,
    PatchedErrorTrackingSettingsApi,
    PatchedErrorTrackingSpikeDetectionConfigApi,
    PatchedErrorTrackingSuppressionRuleApi,
    PatchedErrorTrackingSuppressionRuleUpdateRequestApi,
} from './api.zod.schemas'

export const ErrorTrackingAssignmentRulesCreateBody = ErrorTrackingAssignmentRuleCreateRequestApi

export const ErrorTrackingAssignmentRulesUpdateBody = ErrorTrackingAssignmentRuleUpdateRequestApi

export const ErrorTrackingAssignmentRulesPartialUpdateBody = PatchedErrorTrackingAssignmentRuleUpdateRequestApi

export const ErrorTrackingAssignmentRulesReorderPartialUpdateBody = PatchedErrorTrackingAssignmentRuleApi

export const ErrorTrackingBypassRulesCreateBody = ErrorTrackingBypassRuleCreateRequestApi

export const ErrorTrackingBypassRulesUpdateBody = ErrorTrackingBypassRuleUpdateRequestApi

export const ErrorTrackingBypassRulesPartialUpdateBody = PatchedErrorTrackingBypassRuleUpdateRequestApi

export const ErrorTrackingBypassRulesReorderPartialUpdateBody = PatchedErrorTrackingBypassRuleApi

export const ErrorTrackingExternalReferencesCreateBody = ErrorTrackingExternalReferenceResultApi

export const ErrorTrackingGroupingRulesCreateBody = ErrorTrackingGroupingRuleCreateRequestApi

export const ErrorTrackingGroupingRulesUpdateBody = ErrorTrackingGroupingRuleUpdateRequestApi

export const ErrorTrackingGroupingRulesPartialUpdateBody = PatchedErrorTrackingGroupingRuleUpdateRequestApi

export const ErrorTrackingGroupingRulesReorderPartialUpdateBody = PatchedErrorTrackingGroupingRuleApi

export const ErrorTrackingIssuesUpdateBody = ErrorTrackingIssueWriteApi

export const ErrorTrackingIssuesPartialUpdateBody = PatchedErrorTrackingIssueWriteApi

export const ErrorTrackingIssuesAssignPartialUpdateBody = PatchedErrorTrackingIssueReadApi

export const ErrorTrackingIssuesCohortUpdateBody = ErrorTrackingIssueReadApi

export const ErrorTrackingIssuesMergeCreateBody = ErrorTrackingIssueMergeRequestApi

export const ErrorTrackingIssuesSplitCreateBody = ErrorTrackingIssueSplitRequestApi

export const ErrorTrackingIssuesBulkCreateBody = ErrorTrackingIssueReadApi

/**
 * Fetch one error tracking issue with impact counts, top in_app frame, latest release, and optional sparkline.
 * @summary Get compact error tracking issue details
 */
export const ErrorTrackingQueryIssueCreateBody = ErrorTrackingIssueQueryRequestApi

/**
 * Fetch sampled exception events, stack traces, browser/SDK context, URL, and $session_id values for one issue.
 * @summary List sampled exception events for an error tracking issue
 */
export const ErrorTrackingQueryIssueEventsCreateBody = ErrorTrackingIssueEventsQueryRequestApi

/**
 * List error tracking issues with typed filters and compact aggregate counts.
 * @summary List compact error tracking issues
 */
export const ErrorTrackingQueryIssuesListCreateBody = ErrorTrackingIssuesListQueryRequestApi

export const ErrorTrackingReleasesCreateBody = ErrorTrackingReleaseCreateRequestApi

export const ErrorTrackingReleasesUpdateBody = ErrorTrackingReleaseUpdateRequestApi

export const ErrorTrackingReleasesPartialUpdateBody = PatchedErrorTrackingReleaseUpdateRequestApi

export const ErrorTrackingSettingsUpdateSettingsPartialUpdateBody = PatchedErrorTrackingSettingsApi

export const ErrorTrackingSpikeDetectionConfigUpdateConfigPartialUpdateBody =
    PatchedErrorTrackingSpikeDetectionConfigApi

export const ErrorTrackingStackFramesBatchGetCreateBody = ErrorTrackingStackFrameBatchGetRequestApi

export const ErrorTrackingSuppressionRulesCreateBody = ErrorTrackingSuppressionRuleCreateRequestApi

export const ErrorTrackingSuppressionRulesUpdateBody = ErrorTrackingSuppressionRuleUpdateRequestApi

export const ErrorTrackingSuppressionRulesPartialUpdateBody = PatchedErrorTrackingSuppressionRuleUpdateRequestApi

export const ErrorTrackingSuppressionRulesReorderPartialUpdateBody = PatchedErrorTrackingSuppressionRuleApi

export const ErrorTrackingSymbolSetsFinishUploadUpdateBody = ErrorTrackingSymbolSetFinishUploadApi

export const ErrorTrackingSymbolSetsBulkDeleteCreateBody = ErrorTrackingSymbolSetBulkDeleteApi

export const ErrorTrackingSymbolSetsBulkFinishUploadCreateBody = ErrorTrackingSymbolSetBulkFinishUploadApi

export const ErrorTrackingSymbolSetsBulkStartUploadCreateBody = ErrorTrackingSymbolSetBulkStartUploadApi
