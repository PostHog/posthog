import { render } from '@testing-library/react'

import { ActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { manifest } from '../manifest'

describe('subscription ownership activity descriptions', () => {
    beforeEach(() => initKeaTests())

    it.each([
        ['took_ownership', true, 'Alex took ownership of Weekly report'],
        [
            'transferred_ownership',
            true,
            'Alex transferred ownership of Weekly report from sam@example.com to taylor@example.com',
        ],
        [
            'transferred_ownership',
            false,
            'Alex transferred ownership of Weekly report from the previous owner to the new owner',
        ],
        ['updated', true, 'Alex updated Weekly report'],
    ])('renders %s with owner details: %s', async (activity, withOwners, expected) => {
        const logItem: ActivityLogItem = {
            user: { first_name: 'Alex', last_name: '', email: 'alex@example.com' },
            activity,
            created_at: '2026-01-01T00:00:00Z',
            scope: 'Subscription',
            detail: {
                name: 'Weekly report',
                merge: null,
                trigger: null,
                changes: withOwners
                    ? [
                          {
                              type: ActivityScope.SUBSCRIPTION,
                              action: 'changed',
                              field: 'created_by',
                              before: { id: 2, email: 'sam@example.com' },
                              after: { id: 3, email: 'taylor@example.com' },
                          },
                      ]
                    : [],
            },
        }
        const describer = await manifest.activityDescribers![ActivityScope.SUBSCRIPTION]!()
        const rows = humanize([logItem], () => describer)
        expect(rows).toHaveLength(1)
        const { container } = render(<>{rows[0].description}</>)
        expect(container.textContent).toBe(expected)
        expect(rows[0].summary).toBeTruthy()
    })
})
