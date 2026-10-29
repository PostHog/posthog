import type {
    FeatureFlagConditionGroupSchemaApi,
    FeatureFlagFilterPropertyExistsSchemaApi,
    FeatureFlagFiltersSchemaApi,
    SurveyApi,
} from 'products/surveys/frontend/generated/api.schemas'

export function workflowTriggeredPropertyKey(surveyId: string): string {
    return `$survey_triggered/${surveyId}`
}

function targetingGroups(survey: SurveyApi): FeatureFlagConditionGroupSchemaApi[] {
    const groups = survey.targeting_flag?.filters?.groups
    return Array.isArray(groups) ? (groups as FeatureFlagConditionGroupSchemaApi[]) : []
}

function isWorkflowCondition(property: { key?: string; type?: string; operator?: string }, key: string): boolean {
    return property.key === key && property.type === 'person' && property.operator === 'is_set'
}

/** True when every targeting group requires the person to have been reached by a workflow. */
export function isLimitedToWorkflowRecipients(survey: SurveyApi): boolean {
    const key = workflowTriggeredPropertyKey(survey.id)
    const groups = targetingGroups(survey)
    return (
        groups.length > 0 && groups.every((group) => (group.properties ?? []).some((p) => isWorkflowCondition(p, key)))
    )
}

/** Adds the workflow condition to each existing targeting group, keeping the survey's other conditions. */
export function targetingFiltersLimitedToWorkflowRecipients(survey: SurveyApi): FeatureFlagFiltersSchemaApi {
    const key = workflowTriggeredPropertyKey(survey.id)
    const condition: FeatureFlagFilterPropertyExistsSchemaApi = {
        key,
        type: 'person',
        operator: 'is_set',
        value: 'is_set',
    }
    const groups = targetingGroups(survey)
    if (groups.length === 0) {
        return { groups: [{ properties: [condition], rollout_percentage: 100, variant: null }] }
    }
    return {
        groups: groups.map((group) =>
            (group.properties ?? []).some((p) => isWorkflowCondition(p, key))
                ? group
                : { ...group, properties: [...(group.properties ?? []).filter((p) => p.key !== key), condition] }
        ),
    }
}
