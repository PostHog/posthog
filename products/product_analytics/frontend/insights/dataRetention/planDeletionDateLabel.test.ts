import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { planDeletionDateLabel } from './planDeletionDateLabel'

const RETENTION: EventsRetentionApi = {
    retention_months: 12,
    retained_from: '2025-11-03',
    docs_url: 'https://posthog.com/docs/data/events-retention',
    project_retention_months: null,
    next_deletion_on: '2027-02-03',
    next_deletion_before: '2026-02-01',
    scheduled_pass_on: '2027-02-03',
    first_pass_on: '2027-02-03',
    default_period_deletes: true,
    organization_retention_months: null,
    default_retention_months: 12,
    default_is_grandfathered: false,
    plan_retention_months: 12,
    min_retention_months: 1,
    max_retention_months: 12,
    retention_months_choices: [1, 3, 12],
    next_monthly_cleanup_on: '2026-11-03',
}

describe('planDeletionDateLabel', () => {
    it.each([
        ['formats the date of the next deletion', RETENTION, 'February 3, 2027'],
        ['hides the date while no deletion is scheduled', { ...RETENTION, next_deletion_on: null }, null],
        ['hides the date before the retention loads', null, null],
    ])('%s', (_name, retention, expected) => {
        expect(planDeletionDateLabel(retention)).toEqual(expected)
    })
})
