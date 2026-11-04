import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
} from '~/types'

import { withPropertyFilter } from './withPropertyFilter'

const { And, Or } = FilterLogicalOperator

const filterOn = (key: string): AnyPropertyFilter => ({
    key,
    type: PropertyFilterType.Person,
    operator: PropertyOperator.IsNot,
    value: ['example'],
})
const rule = filterOn('email')
const a = filterOn('a')
const b = filterOn('b')

describe('withPropertyFilter', () => {
    it.each<{
        name: string
        properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined
        expected: AnyPropertyFilter[] | PropertyGroupFilter | null
    }>([
        { name: 'no filters', properties: undefined, expected: [rule] },
        { name: 'a list', properties: [a], expected: [a, rule] },
        {
            name: 'AND groups',
            properties: { type: And, values: [{ type: Or, values: [a, b] }] },
            expected: {
                type: And,
                values: [
                    { type: Or, values: [a, b] },
                    { type: And, values: [rule] },
                ],
            },
        },
        {
            name: 'OR of AND groups',
            properties: {
                type: Or,
                values: [
                    { type: And, values: [a] },
                    { type: And, values: [b] },
                ],
            },
            expected: {
                type: Or,
                values: [
                    { type: And, values: [a, rule] },
                    { type: And, values: [b, rule] },
                ],
            },
        },
        {
            name: 'an empty OR group',
            properties: { type: Or, values: [] },
            expected: { type: And, values: [{ type: And, values: [rule] }] },
        },
        {
            name: 'OR of an OR group',
            properties: { type: Or, values: [{ type: Or, values: [a, b] }] },
            expected: null,
        },
    ])('adds the filter to $name without changing what they match', ({ properties, expected }) => {
        expect(withPropertyFilter(properties, rule)).toEqual(expected)
    })
})
