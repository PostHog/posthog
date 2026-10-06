import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { ActivityDescriber } from './ActivityDescriber'

const makeLogItem = (activity: string, change: Partial<ActivityChange>): ActivityLogItem => ({
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
    },
})

const describedText = (item: ActivityLogItem): string => {
    const { description } = ActivityDescriber(item)
    if (!description) {
        return ''
    }
    const { container } = render(description as JSX.Element)
    return container.textContent || ''
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
})
