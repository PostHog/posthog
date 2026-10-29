import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { planDeletionDateLabel } from './planDeletionDateLabel'

const RETENTION: EventsRetentionApi = {
    retention_months: 12,
    retained_from: '2025-11-03',
    docs_url: 'https://posthog.com/docs/data/events-retention',
    project_retention_months: null,
    organization_retention_months: null,
    plan_retention_months: 12,
    min_retention_months: 1,
    max_retention_months: 12,
    next_deletion_on: '2027-02-03',
}

describe('planDeletionDateLabel', () => {
    it.each([
        ['formats the date while the plan sets the window', RETENTION, 'February 3, 2027'],
        [
            'hides the date while a shorter setting sets the window',
            { ...RETENTION, retention_months: 6, project_retention_months: 6 },
            null,
        ],
        ['hides the date while no deletion is scheduled', { ...RETENTION, next_deletion_on: null }, null],
        ['hides the date before the retention loads', null, null],
    ])('%s', (_name, retention, expected) => {
        expect(planDeletionDateLabel(retention)).toEqual(expected)
    })
})
