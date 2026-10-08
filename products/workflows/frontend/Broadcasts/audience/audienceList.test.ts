import { audienceListCsv, csvListError, parseAudienceList } from './audienceList'

describe('audienceList', () => {
    it.each([
        {
            case: 'emails in mixed case, quotes, commas and duplicates',
            text: 'Ada@Example.com\n"grace@example.com", ada@example.com; linus@example.com\n\n',
            expected: {
                idType: 'email',
                entries: ['ada@example.com', 'grace@example.com', 'linus@example.com'],
                duplicatesRemoved: 1,
            },
        },
        {
            case: 'distinct IDs, kept as typed',
            text: 'User-1\nuser-1\nuser-2',
            expected: { idType: 'distinct_id', entries: ['User-1', 'user-1', 'user-2'], duplicatesRemoved: 0 },
        },
        {
            case: 'a mix of emails and IDs, read as distinct IDs',
            text: 'ada@example.com\nuser-2',
            expected: { idType: 'distinct_id', entries: ['ada@example.com', 'user-2'], duplicatesRemoved: 0 },
        },
    ])('parses $case', ({ text, expected }) => {
        expect(parseAudienceList(text)).toEqual(expected)
    })

    it('writes a CSV the cohort import reads, quoting ids that hold a comma', async () => {
        const csv = audienceListCsv({ idType: 'distinct_id', entries: ['user-1', 'acme, inc'], duplicatesRemoved: 0 })

        expect(await csv.text()).toEqual('distinct_id\nuser-1\n"acme, inc"\n')
    })

    it.each([
        { case: 'an empty file', text: '\n', expected: 'The file is empty.' },
        {
            case: 'columns without an id',
            text: 'name,company\nAda,Acme\n',
            expected: 'The file needs a column named email, distinct_id or person_id.',
        },
        { case: 'a header with no rows', text: 'email\n', expected: 'The file has a header row but no people in it.' },
        { case: 'an email column among others', text: 'Name,Email\nAda,ada@example.com\n', expected: null },
        { case: 'one column of ids without a header', text: 'user-1\nuser-2\n', expected: null },
    ])('checks $case before uploading', ({ text, expected }) => {
        expect(csvListError(text)).toEqual(expected)
    })
})
