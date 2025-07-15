import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

type ErrorTrackingBaseRule = {
    id: string
    filters: UniversalFiltersGroup
}

export type ErrorTrackingSuppressionRule = ErrorTrackingBaseRule

export type ErrorTrackingAssignmentRule = ErrorTrackingBaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
}

export type ErrorTrackingGroupingRule = ErrorTrackingBaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
    description?: string
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
