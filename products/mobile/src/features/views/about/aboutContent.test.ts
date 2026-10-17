import { filterLabel, flattenFilters } from './aboutContent'

describe('about sheet filters', () => {
    test.each([
        [
            'a flat list',
            [{ key: '$host', value: 'app.example.com', operator: 'exact', type: 'event' }],
            ['$host = app.example.com'],
        ],
        [
            'nested AND groups, as the web saves global filters',
            {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [
                            { key: '$browser', value: ['Chrome', 'Safari'], operator: 'is_not', type: 'person' },
                            { key: 'email', operator: 'is_set', type: 'person' },
                        ],
                    },
                ],
            },
            ['$browser ≠ Chrome, Safari', 'email is set'],
        ],
        ['a cohort', [{ type: 'cohort', key: 'id', value: 42 }], ['In cohort 42']],
        ['no filters', undefined, []],
    ])('lists %s', (_name, properties, expected) => {
        expect(flattenFilters(properties).map(filterLabel)).toEqual(expected)
    })
})
