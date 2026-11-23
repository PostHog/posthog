import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { firstExceptionOfNewIssue, firstExceptionsOfNewIssuesUrl } from './tagRuleMatch'

const browserFilter: EventPropertyFilter = {
    key: '$browser',
    value: ['Firefox'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

function linkedSource(url: string): Record<string, any> {
    const query = new URLSearchParams(new URL(url, 'http://localhost').hash.slice(1)).get('q')
    return JSON.parse(query ?? '{}').source
}

describe('firstExceptionsOfNewIssuesUrl', () => {
    // The preview counts only first exceptions of new issues. A link without the same constraint, or that drops the
    // AND/OR type, lists exceptions the count left out.
    it.each([FilterLogicalOperator.And, FilterLogicalOperator.Or])(
        'links to the exceptions the preview counted for a %s rule',
        (type) => {
            const source = linkedSource(firstExceptionsOfNewIssuesUrl({ type, values: [browserFilter] }, '-30d'))

            expect(source).toMatchObject({
                after: '-30d',
                fixedProperties: [{ type, values: [browserFilter] }],
                where: [firstExceptionOfNewIssue('-30d')],
            })
        }
    )
})
