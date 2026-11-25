import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem, Trigger } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { ActivityScope } from '~/types'

import { ActivityDescriber } from './ActivityDescriber'

const makeLogItem = (
    activity: string,
    change: Partial<ActivityChange> | Partial<ActivityChange>[],
    trigger: Trigger | null = null
): ActivityLogItem => ({
    user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    activity,
    created_at: '2026-06-04T00:00:00Z',
    scope: ActivityScope.ERROR_TRACKING_ISSUE,
    item_id: '018f0000-0000-0000-0000-000000000001',
    detail: {
        merge: null,
        trigger,
        name: 'TypeError',
        changes: (Array.isArray(change) ? change : [change]).map(
            (oneChange) =>
                ({
                    type: ActivityScope.ERROR_TRACKING_ISSUE,
                    action: 'changed',
                    ...oneChange,
                }) as ActivityChange
        ),
    },
})

const resolvedToActive: Partial<ActivityChange> = { field: 'status', before: 'resolved', after: 'active' }
const activeToResolved: Partial<ActivityChange> = { field: 'status', before: 'active', after: 'resolved' }

const ingestionTrigger = (payload: Record<string, any>): Trigger => ({
    job_type: 'error_tracking_ingestion',
    job_id: 'notification-1',
    payload: { event_uuid: '018f0000-0000-0000-0000-0000000000aa', ...payload },
})

const describedText = (item: ActivityLogItem): string => {
    const { description } = ActivityDescriber(item)
    if (!description) {
        return ''
    }
    const { container } = render(description as JSX.Element)
    return container.textContent || ''
}

const summaryText = (item: ActivityLogItem): string => {
    const { summary } = ActivityDescriber(item)
    if (!summary) {
        return ''
    }
    const { container } = render(<>{summary.action}</>)
    return container.textContent || ''
}

describe('error tracking ActivityDescriber', () => {
    it.each([
        {
            name: 'an ingestion reopen by a newer release names the release',
            item: makeLogItem(
                'updated',
                resolvedToActive,
                ingestionTrigger({
                    reason: 'new_release',
                    release: { id: 'release-b', version: '2.4.0', project: 'web', created_at: '2026-06-03T00:00:00Z' },
                })
            ),
            summary: 'Reopened by release 2.4.0',
        },
        {
            name: 'an ingestion reopen of an archived issue without a release names the new exception',
            item: makeLogItem(
                'updated',
                { field: 'status', before: 'archived', after: 'active' },
                ingestionTrigger({ reason: 'new_occurrence' })
            ),
            summary: 'Reopened by a new exception',
        },
        {
            name: 'a reopen by a person reads as a status change',
            item: makeLogItem('updated', resolvedToActive),
            summary: 'Changed status from resolved to active',
        },
        {
            name: 'a plain resolve reads as a status change',
            item: makeLogItem('updated', [
                activeToResolved,
                { field: 'resolved_until', before: null, after: 'new_release' },
            ]),
            summary: 'Changed status from active to resolved',
        },
        {
            name: 'a resolve until the next occurrence names the mode',
            item: makeLogItem('updated', [
                activeToResolved,
                { field: 'resolved_until', before: null, after: 'next_occurrence' },
            ]),
            summary: 'Resolved until the next occurrence',
        },
        {
            name: 'a mode change on a resolved issue names the new mode',
            item: makeLogItem('updated', { field: 'resolved_until', before: 'next_occurrence', after: 'new_release' }),
            summary: 'Changed to reopen only in a newer release',
        },
    ])('$name', ({ item, summary }) => {
        expect(summaryText(item)).toEqual(summary)
    })

    it('says when the reopening exception happened', () => {
        const exceptionTimestamp = '2026-06-03T10:15:00Z'
        const text = describedText(
            makeLogItem(
                'updated',
                resolvedToActive,
                ingestionTrigger({ reason: 'new_occurrence', exception_timestamp: exceptionTimestamp })
            )
        )
        expect(text).toContain(
            `after a new exception on ${humanFriendlyDetailedTime(dayjs(exceptionTimestamp), undefined, undefined, {
                timestampStyle: 'absolute',
            })}`
        )
    })

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
