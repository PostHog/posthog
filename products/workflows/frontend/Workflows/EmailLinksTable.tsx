import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { type EmailLinkRow } from './workflowMetricsSummaryLogic'

const EMAIL_LINK_COLUMNS: LemonTableColumns<EmailLinkRow> = [
    {
        title: 'Link',
        key: 'url',
        render: (_: unknown, row: EmailLinkRow) => (
            <div className="flex items-center gap-2">
                {row.truncated ? (
                    // Navigating to a URL that was cut mid-path would land somewhere wrong,
                    // so show it as text rather than something clickable.
                    <span className="break-all" title="This link was too long to store in full">
                        {row.url}…
                    </span>
                ) : (
                    <Link to={row.url} target="_blank" className="break-all">
                        {row.url}
                    </Link>
                )}
                {row.duplicateUrl && row.linkIndex ? (
                    <LemonTag type="muted" title="Another link in this email points to the same page">
                        Position {row.linkIndex}
                    </LemonTag>
                ) : null}
            </div>
        ),
    },
    {
        title: 'Clicks',
        key: 'clicks',
        align: 'right',
        render: (_: unknown, row: EmailLinkRow) => humanFriendlyNumber(row.clicks),
    },
]

export function EmailLinksTable({
    links,
    loading,
    embedded,
    emptyState,
}: {
    links: EmailLinkRow[]
    loading?: boolean
    embedded?: boolean
    emptyState?: string
}): JSX.Element {
    return (
        <LemonTable
            columns={EMAIL_LINK_COLUMNS}
            dataSource={links}
            loading={loading}
            rowKey={(link) => `${link.linkIndex}:${link.url}`}
            size="small"
            embedded={embedded}
            emptyState={emptyState}
        />
    )
}
