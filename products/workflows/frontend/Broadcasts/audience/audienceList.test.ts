import { audienceCohortLaunchError, peopleImportMessage } from './audienceList'

describe('audienceList', () => {
    it.each([
        {
            cohort: 'an uploaded list still matching',
            state: { isStatic: true, isCalculating: true, calculatedBefore: false, failed: false },
            expected: '"List" is still matching people. You can launch when it finishes.',
        },
        {
            cohort: 'an uploaded list that failed to match',
            state: { isStatic: true, isCalculating: false, calculatedBefore: true, failed: true },
            expected: '"List" couldn\'t match its people. Remove it from the recipients, or upload the list again.',
        },
        {
            cohort: 'a matched list',
            state: { isStatic: true, isCalculating: false, calculatedBefore: true, failed: false },
            expected: null,
        },
        {
            cohort: 'a dynamic cohort recalculating',
            state: { isStatic: false, isCalculating: true, calculatedBefore: true, failed: false },
            expected: null,
        },
        {
            cohort: 'a new dynamic cohort before its first calculation',
            state: { isStatic: false, isCalculating: true, calculatedBefore: false, failed: false },
            expected: '"List" is still calculating who\'s in it. You can launch when it finishes.',
        },
    ])('decides whether $cohort blocks launch', ({ state, expected }) => {
        const cohort = { id: 42, name: 'List', count: null, importTotal: null, importUnmatched: null, ...state }
        expect(audienceCohortLaunchError(cohort)).toEqual(expected)
    })

    it.each([
        {
            case: 'nothing skipped',
            dropped: [0, 0, 0],
            expected:
                'Added "List" to the audience. 2 new people were created. Their properties can take a minute to update.',
        },
        {
            case: 'skipped rows',
            dropped: [1, 2, 0],
            expected:
                'Added "List" to the audience. 2 new people were created. Skipped 3 rows: 1 had no valid email, 2 repeated an email or distinct ID. Their properties can take a minute to update.',
        },
    ])('reports an import with $case', ({ dropped: [invalid, duplicate, tooLarge], expected }) => {
        const summary = {
            cohort_id: 42,
            row_count: 2,
            new_people: 2,
            columns: ['email'],
            dropped_invalid_email: invalid,
            dropped_duplicate_email: duplicate,
            dropped_too_large: tooLarge,
        }
        expect(peopleImportMessage('List', summary)).toEqual(expected)
    })
})
