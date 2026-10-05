import { router } from 'kea-router'

import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { unreachablePersonsUrl } from './unreachablePersonsUrl'

describe('unreachablePersonsUrl', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('opens the persons list with named persons, filtered to persons with a missing or blank email', () => {
        router.actions.push(unreachablePersonsUrl())
        const { q } = router.values.hashParams

        expect(router.values.location.pathname).toContain(urls.persons())
        expect(q.full).toBe(true)
        expect(q.source.kind).toBe('ActorsQuery')
        expect(q.source.select).toContain(PERSON_DISPLAY_NAME_COLUMN_NAME)
        expect(q.source.properties).toEqual([
            {
                type: PropertyFilterType.Person,
                key: 'email',
                operator: PropertyOperator.NotRegex,
                value: '[^ \\t\\n\\r]',
            },
        ])
    })
})
