import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { JsonType, UniversalFiltersGroup } from '~/types'

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

export type ErrorTrackingRule = ErrorTrackingSuppressionRule | ErrorTrackingGroupingRule | ErrorTrackingAssignmentRule
export type ErrorTrackingRuleNew = ErrorTrackingRule & { id: 'new' }

export enum ErrorTrackingRuleType {
    Assignment = 'assignment_rules',
    Grouping = 'grouping_rules',
    Suppression = 'suppression_rules',
}

export type ErrorTrackingRulesLogicProps = {
    ruleType: ErrorTrackingRuleType
}
