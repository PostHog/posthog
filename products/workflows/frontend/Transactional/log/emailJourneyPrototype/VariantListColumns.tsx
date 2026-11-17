// PROTOTYPE (ticket #385), throwaway. The list Michael picked: highlights across all emails on top, and a table that
// carries each email's impact. A mini funnel, the conversion, and Replay vision's state sit in columns, each one click
// from the email's impact page.
import { useState } from 'react'

import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { percent } from './impactFixtures'
import { ConversionCell, EmailName, impactUrl, MiniFunnel, ReplayVisionCell, Sparkline } from './ListCells'
import { ListEmail } from './listFixtures'
import { ListHighlights } from './ListHighlights'

export function VariantListColumns({ emails }: { emails: ListEmail[] }): JSX.Element {
    const [watchingAll, setWatchingAll] = useState(false)
    return (
        <div className="flex flex-col gap-4">
            <ListHighlights emails={emails} watchingAll={watchingAll} onWatchAll={() => setWatchingAll(true)} />
            <LemonTable<ListEmail>
                dataSource={emails}
                rowKey="id"
                data-attr="prototype-list-columns"
                columns={[
                    { title: 'Name', key: 'name', render: (_, email) => <EmailName email={email} /> },
                    {
                        title: 'Sent, last 30 days',
                        key: 'sent',
                        render: (_, email) => (
                            <div className="flex items-center gap-2 text-secondary">
                                <Sparkline values={email.daily} />
                                <span className="text-primary font-semibold">{humanFriendlyNumber(email.sent)}</span>
                            </div>
                        ),
                    },
                    {
                        title: 'Opened',
                        key: 'opened',
                        align: 'right',
                        render: (_, email) =>
                            email.opened === null ? (
                                <span className="text-secondary">-</span>
                            ) : (
                                percent(email.opened, email.delivered)
                            ),
                    },
                    {
                        title: 'Clicked',
                        key: 'clicked',
                        align: 'right',
                        render: (_, email) =>
                            email.clicked === null ? (
                                <span className="text-secondary">-</span>
                            ) : (
                                percent(email.clicked, email.delivered)
                            ),
                    },
                    { title: 'Funnel', key: 'funnel', render: (_, email) => <MiniFunnel email={email} /> },
                    { title: 'Converted', key: 'converted', render: (_, email) => <ConversionCell email={email} /> },
                    {
                        title: 'Replay vision',
                        key: 'vision',
                        render: (_, email) => <ReplayVisionCell email={email} watching={watchingAll} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, email) => (
                            <LemonButton size="xsmall" type="secondary" to={impactUrl(email)}>
                                Impact
                            </LemonButton>
                        ),
                    },
                ]}
            />
        </div>
    )
}
