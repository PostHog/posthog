import { WorkflowTemplateTypeFilter, matchesTemplateType, templateTypeForListType } from './workflowTypeFilters'

describe('workflowTypeFilters', () => {
    test.each<[string, string[], WorkflowTemplateTypeFilter, boolean]>([
        ['email is messaging', ['trigger', 'function_email'], 'messaging', true],
        ['sms is messaging', ['trigger', 'function_sms'], 'messaging', true],
        ['push is messaging', ['trigger', 'delay', 'function_push'], 'messaging', true],
        ['slack-only is not messaging', ['trigger', 'function'], 'messaging', false],
        ['slack-only is automation', ['trigger', 'function'], 'automation', true],
        ['slack plus email is not automation', ['trigger', 'function', 'function_email'], 'automation', false],
        ['all matches everything', ['trigger', 'function_email'], 'all', true],
    ])('%s', (_, actionTypes, typeFilter, expected) => {
        expect(
            matchesTemplateType(
                actionTypes.map((type) => ({ type }) as any),
                typeFilter
            )
        ).toBe(expected)
    })

    test.each([
        ['messaging', 'messaging'],
        ['automation', 'automation'],
        ['loop', 'all'],
        ['all', 'all'],
    ] as const)('list type %s opens templates filtered to %s', (listType, expected) => {
        expect(templateTypeForListType(listType)).toBe(expected)
    })
})
