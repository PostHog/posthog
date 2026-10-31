import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { planDeletionDateLabel } from './planDeletionDateLabel'

const RETENTION: EventsRetentionApi = {
    retention_months: 12,
    retained_from: '2025-11-03',
    docs_url: 'https://posthog.com/docs/data/events-retention',
    project_retention_months: null,
    delete_monthly: false,
    next_deletion_on: '2027-02-03',
    next_deletion_before: '2026-02-01',
    scheduled_pass_on: '2027-02-03',
    first_pass_on: '2027-02-03',
    default_window_deletes: true,
    organization_retention_months: null,
    organization_delete_monthly: false,
    plan_retention_months: 12,
    default_retention_months: 12,
    min_retention_months: 1,
    max_retention_months: 12,
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
