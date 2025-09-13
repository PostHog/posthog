import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { JsonType, UniversalFiltersGroup } from '~/types'

type BaseRule = {
    id: string
    filters: UniversalFiltersGroup
    order_key: number
}

export type SuppressionRule = BaseRule

export type AssignmentRule = BaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
    disabled_data: JsonType | null
}

export type GroupingRule = BaseRule & {
    assignee: ErrorTrackingIssueAssignee | null
    disabled_data: JsonType | null
    description?: string
}

export type Rule = SuppressionRule | GroupingRule | AssignmentRule
export type RuleNew = Rule & { id: 'new' }

export enum RuleType {
    Assignment = 'assignment_rules',
    Grouping = 'grouping_rules',
    Suppression = 'suppression_rules',
}

export type RulesLogicProps = {
    ruleType: RuleType
}
