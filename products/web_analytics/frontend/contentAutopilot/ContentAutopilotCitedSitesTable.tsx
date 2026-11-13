import { LemonTable } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type {
    AEOPromptSetDomainApi,
    BrandedSegmentEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

/** The sites the engines cite most. A site opens the answers that cite it. */
export const ContentAutopilotCitedSitesTable = ({
    domains,
    days,
    branded,
}: {
    domains: AEOPromptSetDomainApi[]
    days: number
    branded: BrandedSegmentEnumApi
}): JSX.Element => (
    <LemonTable<AEOPromptSetDomainApi>
        size="small"
        embedded
        dataSource={domains}
        rowKey="domain"
        emptyState="No answer cited a site in this window."
        columns={[
            {
                title: 'Site',
                key: 'domain',
                render: (_, { domain, is_target }) => (
                    <ContentAutopilotSiteLabel domain={domain} isTarget={is_target}>
                        <ContentAutopilotCitationsLink
                            lookup={{ kind: 'domain', value: domain, days, branded }}
                            source="overview-sites"
                        >
                            {domain}
                        </ContentAutopilotCitationsLink>
                    </ContentAutopilotSiteLabel>
                ),
            },
            {
                title: 'Cited in',
                key: 'share_of_answers',
                align: 'right',
                tooltip: 'Share of answers that link to at least one page on the site.',
                render: (_, { share_of_answers, answers }) => (
                    <span className="tabular-nums whitespace-nowrap">
                        {percentage(share_of_answers, 1)}{' '}
                        <span className="text-secondary">({answers.toLocaleString()})</span>
                    </span>
                ),
            },
        ]}
    />
)
