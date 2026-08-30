import type {
    ContentAutopilotProposalApi,
    ContentAutopilotProposalListApi,
    ContentAutopilotRunApi,
    ContentAutopilotSiteProfileApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

export const EXAMPLE_PROFILE: ContentAutopilotSiteProfileApi = {
    id: '00000000-0000-4000-8000-000000000001',
    name: 'Example docs',
    domain: 'https://docs.example.com',
    source_urls: ['https://docs.example.com/sitemap.xml'],
    content_boundaries: ['/docs'],
    brand_rules: ['Use sentence case for headings'],
    search_console_enabled: true,
    delivery_mode: 'github',
    github_repository: 'example/docs',
    base_branch: 'main',
    content_directories: ['contents/docs'],
    url_to_file_convention: '/docs/topic maps to contents/docs/topic.mdx',
    created_at: '2026-08-26T12:00:00Z',
    updated_at: '2026-08-26T12:00:00Z',
}

export const EXAMPLE_SECOND_PROFILE: ContentAutopilotSiteProfileApi = {
    ...EXAMPLE_PROFILE,
    id: '00000000-0000-4000-8000-000000000002',
    name: 'Example blog',
    domain: 'https://blog.example.com',
    source_urls: ['https://blog.example.com/sitemap.xml'],
    content_boundaries: ['/blog'],
    delivery_mode: 'export_only',
    github_repository: '',
    content_directories: [],
}

export const EXAMPLE_RUN: ContentAutopilotRunApi = {
    id: '00000000-0000-4000-8000-000000000101',
    profile_id: EXAMPLE_PROFILE.id,
    run_status: 'completed',
    input_snapshot: {
        captured_at: '2026-08-26T12:00:00Z',
        domain: EXAMPLE_PROFILE.domain,
        search_console_connected: true,
        confidence: 'standard',
    },
    errors: [],
    workflow_id: 'content-autopilot-example',
    triggered_by_id: 1,
    created_at: '2026-08-26T12:00:00Z',
    updated_at: '2026-08-26T12:08:00Z',
    completed_at: '2026-08-26T12:08:00Z',
}

export const EXAMPLE_PROPOSAL: ContentAutopilotProposalApi = {
    id: '00000000-0000-4000-8000-000000000201',
    run_id: EXAMPLE_RUN.id,
    proposal_type: 'page_improvement',
    lifecycle_status: 'ready_for_review',
    title: 'Make the web analytics guide easier to discover',
    target_query: 'web analytics guide',
    target_url: 'https://docs.example.com/docs/web-analytics',
    evidence: [
        {
            opportunity_kind: 'poor_ctr',
            explanation:
                'The page appears for this query, but its click-through rate trails other pages in this range.',
            page_url: 'https://docs.example.com/docs/web-analytics',
            query: 'web analytics guide',
            metrics: { impressions: 1240, clicks: 21, click_through_rate: 0.017, average_position: 6.2 },
        },
    ],
    validation_report: {
        passed: true,
        checks: [
            {
                check_key: 'intent_match',
                label: 'Intent match',
                passed: true,
                message: 'The proposed description matches the observed informational query.',
                blocking: true,
            },
        ],
    },
    content_package: {
        file_path: 'contents/docs/web-analytics.mdx',
        title: 'Web analytics',
        description: 'Understand web traffic, behavior, and conversion with privacy-friendly analytics.',
        slug: 'web-analytics',
        markdown: '# Web analytics',
        frontmatter: [],
        internal_links: [],
        source_notes: [],
    },
    original_markdown: '# Web analytics',
    proposed_markdown: '# Web analytics',
    delivery_state: 'not_delivered',
    delivery_reference: '',
    delivery_error: '',
    pull_request_url: '',
    created_at: '2026-08-26T12:08:00Z',
    updated_at: '2026-08-26T12:08:00Z',
}

export const EXAMPLE_PROPOSAL_LIST: ContentAutopilotProposalListApi = {
    id: EXAMPLE_PROPOSAL.id,
    run_id: EXAMPLE_PROPOSAL.run_id,
    proposal_type: EXAMPLE_PROPOSAL.proposal_type,
    lifecycle_status: EXAMPLE_PROPOSAL.lifecycle_status,
    title: EXAMPLE_PROPOSAL.title,
    target_query: EXAMPLE_PROPOSAL.target_query,
    evidence: EXAMPLE_PROPOSAL.evidence,
    validation_report: EXAMPLE_PROPOSAL.validation_report,
    file_path: EXAMPLE_PROPOSAL.content_package.file_path,
    delivery_state: EXAMPLE_PROPOSAL.delivery_state,
    pull_request_url: EXAMPLE_PROPOSAL.pull_request_url,
    created_at: EXAMPLE_PROPOSAL.created_at,
    updated_at: EXAMPLE_PROPOSAL.updated_at,
}
