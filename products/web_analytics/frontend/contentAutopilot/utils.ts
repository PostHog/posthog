import { parseWebAnalyticsURL } from 'scenes/web-analytics/common'

import type {
    ContentAutopilotOpportunityApi,
    ContentAutopilotProposalListApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

const OPPORTUNITIES_STALE_AFTER_MS = 60 * 60 * 1000

export type ContentAutopilotPageTarget =
    | { isNewPage: true; path: string }
    | { isNewPage: false; path: string; url: string }

export const proposalPagePath = (proposal: Pick<ContentAutopilotProposalListApi, 'file_path'>): string =>
    proposal.file_path ? `/${proposal.file_path.replace(/\.mdx?$/, '')}` : ''

export const pageToUpdate = (
    opportunity: Pick<ContentAutopilotOpportunityApi, 'recommended_type' | 'target_url'>,
    proposal: ContentAutopilotProposalListApi | undefined,
    siteOrigin: string
): ContentAutopilotPageTarget | null => {
    const draftedPath = proposal && proposal.lifecycle_status !== 'generating' ? proposalPagePath(proposal) : ''
    if (draftedPath) {
        return proposal?.proposal_type === 'new_content'
            ? { isNewPage: true, path: draftedPath }
            : { isNewPage: false, path: draftedPath, url: `${siteOrigin.replace(/\/$/, '')}${draftedPath}` }
    }
    if (opportunity.recommended_type === 'page_improvement' && opportunity.target_url) {
        return {
            isNewPage: false,
            path: parseWebAnalyticsURL(opportunity.target_url).pathname ?? opportunity.target_url,
            url: opportunity.target_url,
        }
    }
    return null
}

export const opportunitiesNeedRefresh = (
    opportunities: Pick<ContentAutopilotOpportunityApi, 'last_refreshed_at'>[],
    now: number
): boolean => {
    const refreshedAt = opportunities
        .map(({ last_refreshed_at }) => Date.parse(last_refreshed_at))
        .filter((time) => !Number.isNaN(time))
    return refreshedAt.length === 0 || now - Math.max(...refreshedAt) > OPPORTUNITIES_STALE_AFTER_MS
}
