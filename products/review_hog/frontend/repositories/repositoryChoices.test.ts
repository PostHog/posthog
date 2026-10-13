import type {
    ReviewProjectSettingsApi,
    ReviewRepositoryOverviewEntryApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { myChoiceNote, myChoiceOptions, myChoiceValue, projectRuleSummary } from './repositoryChoices'

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
        repository_result: { flash: false, reason: 'project_opt_in' },
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

    it.each([
        {
            name: 'the select alone explains a row the rules decide',
            entry: entry({}),
            note: null,
        },
        {
            name: 'a default that agrees with the repository adds nothing',
            entry: entry({
                my_result: { flash: true, reason: 'own_default' },
                inherited_result: { flash: true, reason: 'own_default' },
                repository_result: { flash: true, reason: 'repository_everyone' },
            }),
            note: null,
        },
        {
            name: 'a default that overrides the project rule leaves the note to the page notice',
            entry: entry({
                my_result: { flash: true, reason: 'own_default' },
                inherited_result: { flash: true, reason: 'own_default' },
            }),
            note: null,
        },
        {
            name: 'a default that overrides a repository exception names what the exception gives',
            entry: entry({
                exception: { flash_for: 'off', people: [] },
                my_result: { flash: true, reason: 'own_default' },
                inherited_result: { flash: true, reason: 'own_default' },
                repository_result: { flash: false, reason: 'repository_opt_in' },
            }),
            note: 'Your default. Without it: off (repository exception)',
        },
        {
            name: 'an own choice names what applies without it, and where that comes from',
            entry: entry({
                my_choice: 'off',
                my_choice_id: 'choice-1',
                my_result: { flash: false, reason: 'own_repository_choice' },
                inherited_result: { flash: true, reason: 'repository_everyone' },
                repository_result: { flash: true, reason: 'repository_everyone' },
            }),
            note: 'Your choice. Without it: on (repository exception)',
        },
    ])('note: $name', ({ entry: picked, note }) => {
        expect(myChoiceNote(picked)).toEqual(note)
    })

    it.each([
        { flashFor: 'everyone', kinds: ['excepted', 'listed'], summary: 'Project rule: everyone, except 1 person.' },
        { flashFor: 'everyone', kinds: [], summary: 'Project rule: everyone.' },
        { flashFor: 'listed', kinds: ['listed', 'listed', 'excepted'], summary: 'Project rule: 2 selected people.' },
        { flashFor: 'off', kinds: ['listed'], summary: 'Project rule: people who opt in.' },
    ] as const)('project rule summary counts only the list $flashFor reads', ({ flashFor, kinds, summary }) => {
        const project = {
            flash_for: flashFor,
            people: kinds.map((kind, index) => ({ id: `person-${index}`, kind })),
        } as unknown as ReviewProjectSettingsApi

        expect(projectRuleSummary(project)).toEqual(summary)
    })
})
