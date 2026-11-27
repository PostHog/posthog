import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSetDomainApi,
    BrandedSegmentEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

/** The sites the engines cite most. A site opens the answers that cite it. */
export const ContentAutopilotCitedSitesTable = ({
    domains,
    dateFrom,
    dateTo,
    branded,
}: {
    domains: AEOPromptSetDomainApi[]
    /** The window of the report, so a row opens the same answers the report counted. */
    dateFrom: string
    dateTo: string
    branded: BrandedSegmentEnumApi
}): JSX.Element => (
    <AiVisibilityTable<AEOPromptSetDomainApi>
        size="small"
        embedded
        dataSource={domains}
        rowKey="domain"
        emptyState="No answer cited a site in this window."
        columns={[
            {
                title: 'Site',
                key: 'domain',
                className: 'w-full max-w-0',
                render: (_, { domain, is_target }) => (
                    <ContentAutopilotSiteLabel domain={domain} isTarget={is_target}>
                        <ContentAutopilotCitationsLink
                            lookup={{ kind: 'domain', value: domain, dateFrom, dateTo, branded }}
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
                    <ContentAutopilotRateBar
                        rate={share_of_answers}
                        tooltip={`Cited in ${pluralize(answers, 'answer')}`}
                    />
                ),
            },
        ]}
    />
)
