import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { myChoiceOptions, myChoiceValue } from './repositoryChoices'

function entry(overrides: Partial<ReviewRepositoryOverviewEntryApi>): ReviewRepositoryOverviewEntryApi {
    return {
        full_name: 'example-org/web',
        github_repo_id: 1001,
        owner: 'this_project',
        owner_project: null,
        in_project: true,
        selected: false,
        repository_id: null,
        exception: null,
        my_choice: null,
        my_choice_id: null,
        my_result: { flash: false, reason: 'project_opt_in' },
        inherited_result: { flash: false, reason: 'project_opt_in' },
        ...overrides,
    }
}

describe('repositoryChoices', () => {
    it.each([
        {
            name: 'no stored choice follows',
            entry: entry({}),
            value: 'follow',
            options: ['follow', 'flash'],
        },
        {
            name: 'a choice that differs from the inherited value is selected',
            entry: entry({ my_choice: 'flash', my_choice_id: 'choice-1' }),
            value: 'flash',
            options: ['follow', 'flash'],
        },
        {
            name: 'a choice equal to the inherited value stays selected and listed',
            entry: entry({ my_choice: 'off', my_choice_id: 'choice-1' }),
            value: 'off',
            options: ['follow', 'flash', 'off'],
        },
    ])('my choice: $name', ({ entry: picked, value, options }) => {
        expect(myChoiceValue(picked)).toEqual(value)
        expect(myChoiceOptions(picked).map((option) => option.value)).toEqual(options)
    })
})
