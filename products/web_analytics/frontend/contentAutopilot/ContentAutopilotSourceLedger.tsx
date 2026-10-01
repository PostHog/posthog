import { LemonTable, Link } from '@posthog/lemon-ui'

import type { ContentAutopilotSourceLedgerEntryApi } from 'products/web_analytics/frontend/generated/api.schemas'

export interface ContentAutopilotSourceLedgerProps {
    entries: ContentAutopilotSourceLedgerEntryApi[]
    notes: string[]
}

export const ContentAutopilotSourceLedger = ({ entries, notes }: ContentAutopilotSourceLedgerProps): JSX.Element => (
    <div className="flex flex-col gap-3">
        <p className="m-0 text-muted text-sm">Each fact in the draft and the page that backs it up.</p>
        <LemonTable
            dataSource={entries}
            rowKey={(entry, index) => `${index}-${entry.claim}-${entry.source_url}`}
            emptyState="The draft doesn't make any claims that need a source."
            columns={[
                { title: 'Claim', key: 'claim', render: (_, entry) => <span className="text-sm">{entry.claim}</span> },
                {
                    title: 'Source',
                    key: 'source',
                    render: (_, entry) => (
                        <div className="text-sm py-1">
                            <Link to={entry.source_url} target="_blank">
                                {entry.source_url}
                            </Link>
                            <blockquote className="m-0 mt-1 text-muted">{entry.quote}</blockquote>
                        </div>
                    ),
                },
            ]}
        />
        {notes.length > 0 ? (
            <section>
                <h4 className="mb-1">Research notes</h4>
                <ul className="list-disc pl-5 m-0 text-sm text-muted">
                    {notes.map((note) => (
                        <li key={note}>{note}</li>
                    ))}
                </ul>
            </section>
        ) : null}
    </div>
)
