import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { JsonType, UniversalFiltersGroup } from '~/types'

import type {
    ErrorTrackingIssueSeverityRuleEnumApi,
    ErrorTrackingIssueTagRuleApi,
    ErrorTrackingSeverityRuleApi,
} from '../../../generated/api.schemas'

export type ErrorTrackingBaseRule = {
    id: string
    filters: UniversalFiltersGroup
    order_key: number
    disabled_data: JsonType | null
    created_at?: string
    updated_at?: string
}

export type ErrorTrackingSuppressionRule = ErrorTrackingBaseRule & {
    sampling_rate: number
}

export type ErrorTrackingAssignmentRule = ErrorTrackingBaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
}

export type ErrorTrackingGroupingRule = ErrorTrackingBaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
    description?: string
    issue?: { id: string; name: string | null } | null
}

export type ErrorTrackingBypassRule = ErrorTrackingBaseRule

export type ErrorTrackingSeverityRule = ErrorTrackingBaseRule & Pick<ErrorTrackingSeverityRuleApi, 'severity'>

export type ErrorTrackingSeverityRuleNew = Omit<ErrorTrackingSeverityRule, 'id' | 'severity'> & {
    id: 'new'
    severity: ErrorTrackingIssueSeverityRuleEnumApi | null
}

export type ErrorTrackingTagRule = Omit<ErrorTrackingBaseRule, 'disabled_data'> &
    Pick<ErrorTrackingIssueTagRuleApi, 'key' | 'label' | 'description' | 'disabled_data'>

export type ErrorTrackingTagRuleNew = Omit<ErrorTrackingTagRule, 'id' | 'key'> & { id: 'new' }

export type ErrorTrackingRule =
    | ErrorTrackingSuppressionRule
    | ErrorTrackingGroupingRule
    | ErrorTrackingAssignmentRule
    | ErrorTrackingBypassRule
    | ErrorTrackingSeverityRule
    | ErrorTrackingSeverityRuleNew
    | ErrorTrackingTagRule
    | ErrorTrackingTagRuleNew
export type ErrorTrackingRuleNew = ErrorTrackingRule & { id: 'new' }

export enum ErrorTrackingRuleType {
    Assignment = 'assignment_rules',
    Bypass = 'bypass_rules',
    Grouping = 'grouping_rules',
    Severity = 'severity_rules',
    Suppression = 'suppression_rules',
    Tag = 'tag_rules',
}

export type ErrorTrackingRulesLogicProps = {
    ruleType: ErrorTrackingRuleType
}
