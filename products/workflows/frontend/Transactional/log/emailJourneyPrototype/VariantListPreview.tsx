// PROTOTYPE (ticket #385), throwaway. List option L2: the table stays close to today's, with one conversion column.
// Opening a row shows that email's funnel, its top problem, and one-click actions, without leaving the list.
import { IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ConversionCell, EmailName, impactUrl, MiniFunnel, ReplayVisionCell, Sparkline } from './ListCells'
import { ListEmail } from './listFixtures'

function RowPreview({ email }: { email: ListEmail }): JSX.Element {
    return (
        <div className="flex flex-col @3xl:flex-row gap-6 p-4 bg-surface-secondary" data-attr="prototype-list-preview">
            <div className="@3xl:flex-[3] min-w-0 flex flex-col gap-2">
                <span className="text-sm font-semibold">
                    From send to {email.goal ? `"${email.goal}"` : 'conversion'}, last 30 days
                </span>
                <MiniFunnel email={email} large />
            </div>
            <div className="@3xl:flex-[2] min-w-0 flex flex-col gap-2">
                <span className="text-sm font-semibold">What people did after clicking</span>
                {email.scanner?.topProblem ? (
                    <span className="text-sm">
                        Most common problem: <strong>{email.scanner.topProblem}</strong>
                    </span>
                ) : (
                    <span className="text-sm text-secondary">
                        Replay vision isn't watching this email's sessions yet.
                    </span>
                )}
                <div className="flex flex-wrap gap-2">
                    <LemonButton size="small" type="primary" to={impactUrl(email)}>
                        Open impact
                    </LemonButton>
                    {email.landed ? (
                        <LemonButton size="small" type="secondary" icon={<IconPlayFilled />} to={urls.replay()}>
                            Recordings
                        </LemonButton>
                    ) : null}
                    <ReplayVisionCell email={email} />
                </div>
            </div>
        </div>
    )
}

export function VariantListPreview({ emails }: { emails: ListEmail[] }): JSX.Element {
    return (
        <LemonTable<ListEmail>
            dataSource={emails}
            rowKey="id"
            data-attr="prototype-list-preview-table"
            expandable={{
                expandedRowRender: (email) => <RowPreview email={email} />,
                rowExpandable: () => true,
                isRowExpanded: (_, index) => (index === 0 ? true : -1),
            }}
            columns={[
                { title: 'Name', key: 'name', render: (_, email) => <EmailName email={email} /> },
                {
                    title: 'Tags',
                    key: 'tags',
                    render: (_, email) => (
                        <span className="flex flex-wrap gap-1">
                            {email.tags.map((tag) => (
                                <LemonTag key={tag} size="small">
                                    {tag}
                                </LemonTag>
                            ))}
                        </span>
                    ),
                },
                {
                    title: 'Last 30 days',
                    key: 'sent',
                    render: (_, email) => (
                        <div className="flex items-center gap-2 text-secondary">
                            <Sparkline values={email.daily} />
                            <span className="text-primary">{humanFriendlyNumber(email.sent)} sent</span>
                        </div>
                    ),
                },
                { title: 'Converted', key: 'converted', render: (_, email) => <ConversionCell email={email} /> },
            ]}
        />
    )
}
