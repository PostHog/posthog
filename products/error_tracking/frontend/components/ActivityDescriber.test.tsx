import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogDetail, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { ActivityDescriber } from './ActivityDescriber'

type LogItemOverrides = Partial<Omit<ActivityLogItem, 'detail'>> & { detail?: Partial<ActivityLogDetail> }

const makeLogItem = (
    activity: string,
    change: Partial<ActivityChange>,
    { detail, ...overrides }: LogItemOverrides = {}
): ActivityLogItem => ({
    user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    activity,
    created_at: '2026-06-04T00:00:00Z',
    scope: ActivityScope.ERROR_TRACKING_ISSUE,
    item_id: '018f0000-0000-0000-0000-000000000001',
    detail: {
        merge: null,
        trigger: null,
        name: 'TypeError',
        changes: [
            {
                type: ActivityScope.ERROR_TRACKING_ISSUE,
                action: 'changed',
                ...change,
            } as ActivityChange,
        ],
        ...detail,
    },
    ...overrides,
})

const systemActor: LogItemOverrides = { user: undefined, is_system: true }

const describedText = (item: ActivityLogItem): string => {
    const { description } = ActivityDescriber(item)
    if (!description) {
        return ''
    }
    const { container } = render(description as JSX.Element)
    return (container.textContent || '').replace(/\s+/g, ' ').trim()
}

describe('error tracking ActivityDescriber', () => {
    it('describes merged rows instead of dropping them', () => {
        const text = describedText(
            makeLogItem('merged', {
                action: 'merged',
                field: 'merged_issue_ids',
                after: ['018f0000-0000-0000-0000-000000000002', '018f0000-0000-0000-0000-000000000003'],
            })
        )
        expect(text).toContain('merged 2 issues into')
        expect(text).toContain('TypeError')
    })

    it('describes split rows instead of dropping them', () => {
        const text = describedText(
            makeLogItem('split', {
                action: 'split',
                field: 'split_issue_ids',
                after: ['018f0000-0000-0000-0000-000000000002'],
            })
        )
        expect(text).toContain('split')
        expect(text).toContain('a new issue')
    })

    it.each<{ name: string; overrides: LogItemOverrides; expected: string }>([
        {
            name: 'an auto-resolve as PostHog with its number of days',
            overrides: {
                ...systemActor,
                detail: { context: { reason: { kind: 'auto_resolve', after_days: 14 } } },
            },
            expected: 'PostHog resolved TypeError automatically after 14 days without exceptions',
        },
        {
            name: 'an auto-resolve after a single day in the singular',
            overrides: {
                ...systemActor,
                detail: { context: { reason: { kind: 'auto_resolve', after_days: 1 } } },
            },
            expected: 'PostHog resolved TypeError automatically after 1 day without exceptions',
        },
        {
            name: 'a manual resolve as the user who made it',
            overrides: {},
            expected: 'Ada Lovelace changed status of TypeError from active to resolved',
        },
        {
            name: 'a system status change without a reason as PostHog',
            overrides: systemActor,
            expected: 'PostHog changed status of TypeError from active to resolved',
        },
    ])('describes $name', ({ overrides, expected }) => {
        const text = describedText(
            makeLogItem('updated', { field: 'status', before: 'active', after: 'resolved' }, overrides)
        )
        expect(text).toBe(expected)
    })
})
