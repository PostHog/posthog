import { LemonTable } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type { AEOPromptSetDomainApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotSiteLabel } from './ContentAutopilotSiteLabel'

export const ContentAutopilotCitedSitesTable = ({ domains }: { domains: AEOPromptSetDomainApi[] }): JSX.Element => (
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
                    <ContentAutopilotSiteLabel domain={domain} isTarget={is_target} />
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
