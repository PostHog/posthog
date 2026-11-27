import { IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { AEOBrandCitedSiteApi, BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'
import { CitedSiteRelationEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { REPORT_TABLE_PAGE_SIZE } from './aiVisibilityTablePaging'
import { AiVisibilityTag, type AiVisibilityTagProps } from './AiVisibilityTag'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

const RELATION_TAGS: Record<CitedSiteRelationEnumApi, { label: string; type: AiVisibilityTagProps['type'] }> = {
    [CitedSiteRelationEnumApi.Owned]: { label: 'Owned', type: 'success' },
    [CitedSiteRelationEnumApi.Competitor]: { label: 'Competitor', type: 'warning' },
    [CitedSiteRelationEnumApi.Other]: { label: 'Other', type: 'muted' },
}

const SHARE_GRID = 'grid list-none grid-cols-[minmax(0,1fr)_minmax(8rem,40%)] items-center gap-3'

/** The sites the answers naming a brand cite, by domain. A site expands to its pages cited most. */
export const ContentAutopilotBrandCitedSites = ({
    sites,
    dateFrom,
    dateTo,
    branded,
    engine,
    topic,
}: {
    sites: AEOBrandCitedSiteApi[]
    dateFrom: string
    dateTo: string
    branded: BrandedSegmentEnumApi
    /** The engine and topic filters of the page, so a site or page opens the same answers it counted. */
    engine: string | null
    topic: string | null
}): JSX.Element => (
    <AiVisibilityCard title="Sites cited next to the brand">
        <AiVisibilityTable<AEOBrandCitedSiteApi>
            size="small"
            embedded
            data-attr="content-autopilot-brand-cited-sites"
            pagination={{ pageSize: REPORT_TABLE_PAGE_SIZE }}
            emptyState="The answers that name this brand cite no site in this date range."
            dataSource={sites}
            rowKey="domain"
            expandable={{
                noIndent: true,
                rowExpandable: (site) => site.pages.length > 0,
                expandedRowRender: (site) => (
                    <ul className="m-0 flex flex-col gap-1 px-3 py-2" data-attr="content-autopilot-brand-cited-pages">
                        {site.pages.map((page) => (
                            <li key={page.url} className={SHARE_GRID}>
                                <span className="flex min-w-0 items-center gap-1">
                                    <ContentAutopilotCitationsLink
                                        lookup={{
                                            kind: 'url',
                                            value: page.url,
                                            dateFrom,
                                            dateTo,
                                            branded,
                                            engine,
                                            topic,
                                        }}
                                        source="brand-cited-pages"
                                        title={page.url}
                                    >
                                        {page.url.replace(/^https?:\/\//, '')}
                                    </ContentAutopilotCitationsLink>
                                    <Button
                                        size="icon-sm"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={page.url} target="_blank" />}
                                        aria-label="Open the page"
                                        tooltip="Open the page"
                                        data-attr="content-autopilot-brand-cited-page-open"
                                    >
                                        <IconExternal />
                                    </Button>
                                </span>
                                <ContentAutopilotRateBar rate={page.share_of_answers} />
                            </li>
                        ))}
                    </ul>
                ),
            }}
            columns={[
                {
                    title: 'Site',
                    key: 'domain',
                    className: 'w-full max-w-0',
                    render: (_, site) => (
                        <ContentAutopilotSiteLabel domain={site.domain} isTarget={false}>
                            <ContentAutopilotCitationsLink
                                lookup={{
                                    kind: 'domain',
                                    value: site.domain,
                                    dateFrom,
                                    dateTo,
                                    branded,
                                    engine,
                                    topic,
                                }}
                                source="brand-cited-sites"
                            >
                                {site.domain}
                            </ContentAutopilotCitationsLink>
                        </ContentAutopilotSiteLabel>
                    ),
                },
                {
                    title: 'Type',
                    key: 'relation',
                    tooltip:
                        'Owned is the brand’s own site. Competitor is your site or a competitor other than this brand.',
                    render: (_, site) => {
                        const tag = RELATION_TAGS[site.relation]
                        return (
                            <AiVisibilityTag type={tag.type} className="whitespace-nowrap">
                                {tag.label}
                            </AiVisibilityTag>
                        )
                    },
                },
                {
                    title: 'Cited in',
                    key: 'share_of_answers',
                    align: 'right',
                    tooltip: 'Share of the answers naming the brand that link to at least one page on the site.',
                    sorter: (a, b) => a.share_of_answers - b.share_of_answers,
                    render: (_, site) => <ContentAutopilotRateBar rate={site.share_of_answers} />,
                },
            ]}
        />
    </AiVisibilityCard>
)
