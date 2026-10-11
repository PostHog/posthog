import { audienceCohortLaunchError, csvListError } from './audienceList'

describe('audienceList', () => {
    it.each([
        { case: 'an empty file', text: '\n', expected: 'The file is empty.' },
        {
            case: 'columns without an id',
            text: 'name,company\nAda,Acme\n',
            expected: 'The file needs a column named email, distinct_id or person_id.',
        },
        { case: 'a header with no rows', text: 'email\n', expected: 'The file has a header row but no people in it.' },
        { case: 'an email column among others', text: 'Name,Email\nAda,ada@example.com\n', expected: null },
        { case: 'a person-id column among others', text: 'person-id,name\nabc,Ada\n', expected: null },
        {
            case: 'an id name only inside a quoted header',
            text: '"name,email",company\nAda,Acme\n',
            expected: 'The file needs a column named email, distinct_id or person_id.',
        },
        { case: 'one column of ids without a header', text: 'user-1\nuser-2\n', expected: null },
    ])('checks $case before uploading', ({ text, expected }) => {
        expect(csvListError(text)).toEqual(expected)
    })

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
})
