// PROTOTYPE (ticket #385), throwaway. Each link in the email: who clicked, the sessions it started, who converted.
import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ImpactData, ImpactLink, percent } from './impactFixtures'
import { LINK_TAG_DETAIL } from './ImpactFunnel'

export function ImpactLinkTable({ data }: { data: ImpactData }): JSX.Element {
    const topFinding = (link: ImpactLink): string | null =>
        data.scanner?.findings.find((finding) => finding.linkKey === link.key && finding.tone === 'problem')?.title ??
        null

    return (
        <LemonTable
            dataSource={data.links}
            rowKey="key"
            size="small"
            emptyState="Clicks aren't tracked for this email, so there's nothing per link."
            columns={[
                {
                    title: 'Link',
                    key: 'link',
                    render: (_, link) => (
                        <div className="flex flex-col py-1">
                            <span className="font-semibold">{link.label}</span>
                            <span className="text-xs text-secondary">{link.url.replace('https://', '')}</span>
                        </div>
                    ),
                },
                {
                    title: 'Clicked',
                    key: 'clicked',
                    align: 'right',
                    render: (_, link) => humanFriendlyNumber(link.clickedPeople),
                },
                {
                    title: 'Sessions',
                    key: 'sessions',
                    align: 'right',
                    render: (_, link) =>
                        !link.tagged ? (
                            <Tooltip
                                title={`This link leaves ${data.sendingDomain.replace(/^mail\./, '')}, so PostHog can't follow it.`}
                            >
                                <LemonTag type="muted">Off your site</LemonTag>
                            </Tooltip>
                        ) : link.sessions === null ? (
                            <Tooltip title={LINK_TAG_DETAIL}>
                                <LemonTag type="muted">Needs link tagging</LemonTag>
                            </Tooltip>
                        ) : (
                            humanFriendlyNumber(link.sessions)
                        ),
                },
                {
                    title: data.goal?.event ?? 'Converted',
                    key: 'converted',
                    align: 'right',
                    render: (_, link) =>
                        link.converted === null ? (
                            <span className="text-secondary">-</span>
                        ) : (
                            <span>
                                {humanFriendlyNumber(link.converted)}{' '}
                                <span className="text-xs text-secondary">
                                    {percent(link.converted, link.clickedPeople)}
                                </span>
                            </span>
                        ),
                },
                {
                    title: 'Most common problem',
                    key: 'finding',
                    render: (_, link) => {
                        const finding = topFinding(link)
                        return finding ? (
                            <span className="text-sm">{finding}</span>
                        ) : (
                            <span className="text-secondary">-</span>
                        )
                    },
                },
                {
                    key: 'actions',
                    width: 0,
                    render: (_, link) =>
                        link.tagged && link.sessions ? (
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                to={urls.replay()}
                                tooltip="Recordings of the sessions this link started"
                            >
                                Recordings
                            </LemonButton>
                        ) : null,
                },
            ]}
        />
    )
}
