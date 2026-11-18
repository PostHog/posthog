import { TZLabel } from 'lib/components/TZLabel'
import { CATEGORY_LABELS } from 'lib/utils/botDetection'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { QueryContextColumn } from '~/queries/types'

import { AiBrandLogo } from './AiBrandLogo'

const categoryColumn: QueryContextColumn = {
    title: 'Category',
    render: ({ value }) => (
        <span>{(CATEGORY_LABELS as Record<string, string>)[String(value ?? '')] ?? String(value ?? '')}</span>
    ),
}

const requestsColumn: QueryContextColumn = {
    title: 'Requests',
    align: 'right',
    render: ({ value }) => (
        <span className="tabular-nums" translate="no">
            {humanFriendlyNumber(Number(value ?? 0))}
        </span>
    ),
}

const crawlersColumn: QueryContextColumn = { ...requestsColumn, title: 'Crawlers' }

const crawlerColumn: QueryContextColumn = {
    title: 'Crawler',
    render: ({ value }) => {
        const name = String(value ?? '')
        return (
            <span className="flex items-center gap-2 min-w-0">
                <AiBrandLogo name={name} size="sm" />
                <span className="truncate">{name}</span>
            </span>
        )
    },
}

const lastSeenColumn: QueryContextColumn = {
    title: 'Last seen',
    render: ({ value }) => (value ? <TZLabel time={String(value)} /> : <span className="text-secondary">-</span>),
}

export const CRAWLER_COLUMNS: Record<string, QueryContextColumn> = {
    Crawler: crawlerColumn,
    Category: categoryColumn,
    Requests: requestsColumn,
    Crawlers: crawlersColumn,
    'Last seen': lastSeenColumn,
}
