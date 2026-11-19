import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import { isLimitedToWorkflowRecipients, targetingFiltersLimitedToWorkflowRecipients } from './workflowSurveyTargeting'

const CONDITION = { key: '$survey_triggered/s1', type: 'person', operator: 'is_set', value: 'is_set' }
const EMAIL = { key: 'email', type: 'person', operator: 'icontains', value: '@example.com' }

const survey = (groups?: unknown[]): SurveyApi =>
    ({ id: 's1', targeting_flag: groups ? { filters: { groups } } : null }) as unknown as SurveyApi

describe('workflow survey targeting', () => {
    it.each([
        ['no targeting flag', undefined, [{ properties: [CONDITION], rollout_percentage: 100, variant: null }]],
        [
            'existing conditions are kept',
            [{ properties: [EMAIL], rollout_percentage: 50 }],
            [{ properties: [EMAIL, CONDITION], rollout_percentage: 50 }],
        ],
        ['already limited', [{ properties: [CONDITION] }], [{ properties: [CONDITION] }]],
        [
            'an excluding workflow condition is replaced',
            [{ properties: [EMAIL, { ...CONDITION, operator: 'is_not_set', value: 'is_not_set' }] }],
            [{ properties: [EMAIL, CONDITION] }],
        ],
    ])('limits %s to workflow recipients', (_, groups, expected) => {
        const filters = targetingFiltersLimitedToWorkflowRecipients(survey(groups))
        expect(filters.groups).toEqual(expected)
        expect(isLimitedToWorkflowRecipients(survey(filters.groups))).toBe(true)
    })

    it('is not limited while any group lacks the condition', () => {
        expect(isLimitedToWorkflowRecipients(survey([{ properties: [CONDITION] }, { properties: [EMAIL] }]))).toBe(
            false
        )
    })
})
