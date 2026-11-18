import { PropertyFilterType, PropertyOperator } from '~/types'

import { operationFilterGroup } from './operationFilters'

describe('operationFilterGroup', () => {
    // A bare "GET" span name matches every route the service serves; the route keeps the link to one endpoint.
    test('narrows a bare-method span name to its route', () => {
        const group = operationFilterGroup('GET', null, { attribute: 'http.route', value: '/users/:id' })

        expect(group.values[0]).toEqual({
            type: 'AND',
            values: [
                { type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: ['GET'] },
                {
                    type: PropertyFilterType.SpanAttribute,
                    key: 'http.route',
                    operator: PropertyOperator.Exact,
                    value: ['/users/:id'],
                },
            ],
        })
    })

    // The endpoints table gives http.route precedence, so a url.template row excludes spans that set http.route.
    test('excludes spans that set a higher-precedence route attribute', () => {
        const group = operationFilterGroup('GET', null, { attribute: 'url.template', value: '/users/{id}' })

        expect(group.values[0]).toEqual({
            type: 'AND',
            values: [
                { type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: ['GET'] },
                {
                    type: PropertyFilterType.SpanAttribute,
                    key: 'url.template',
                    operator: PropertyOperator.Exact,
                    value: ['/users/{id}'],
                },
                { type: PropertyFilterType.SpanAttribute, key: 'http.route', operator: PropertyOperator.IsNotSet },
            ],
        })
    })
})
