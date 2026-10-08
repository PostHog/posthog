import { csvListError } from './audienceList'

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
})
