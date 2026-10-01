import type {
    ContentAutopilotOpportunityApi,
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
}

export const EXAMPLE_RUN: ContentAutopilotRunApi = {
    id: '00000000-0000-4000-8000-000000000101',
    profile_id: EXAMPLE_PROFILE.id,
    run_status: 'completed',
    input_snapshot: {
        domain: EXAMPLE_PROFILE.domain,
        confidence: 'standard',
    },
    errors: [],
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
        frontmatter: [],
        internal_links: [],
        source_notes: [],
    },
    original_markdown: '# Web analytics',
    proposed_markdown: '# Web analytics',
    brief: {
        intent: 'Decide whether a privacy-friendly web analytics tool covers their needs.',
        audience: 'Marketers and founders comparing analytics tools',
        recommended_type: 'page_improvement',
        working_title: 'Web analytics',
        outline: ['What web analytics tracks', 'How it handles privacy', 'Frequently asked questions'],
        questions_to_answer: ['Does it work without cookies?'],
        competitor_coverage: ['Cookieless tracking setup'],
        engine_answer_summary: 'Assistants recommend other tools and do not mention cookieless mode.',
    },
    source_ledger: [
        {
            claim: 'Web analytics works without cookies.',
            source_url: 'https://docs.example.com/docs/web-analytics/cookieless',
            quote: 'You can run web analytics without cookies.',
        },
    ],
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
    created_at: EXAMPLE_PROPOSAL.created_at,
    updated_at: EXAMPLE_PROPOSAL.updated_at,
}

const EXAMPLE_GAP: ContentAutopilotOpportunityApi['gap'] = {
    checks: 9,
    cited_checks: 0,
    mentioned_checks: 0,
    citation_rate: 0,
    engines: ['claude-web-search', 'openai-web-search', 'exa-answer'],
    engines_not_citing: ['claude-web-search', 'openai-web-search', 'exa-answer'],
    competitor_urls: ['https://rival.example.com/replay'],
    competitor_domains: ['rival.example.com', 'reviews.example.org'],
    engine_search_queries: ['open source session replay', 'session replay self hosted'],
    our_cited_urls: [],
    latest_answers: [],
    last_checked_at: '2026-08-26T09:00:00Z',
}

export const EXAMPLE_OPPORTUNITIES: ContentAutopilotOpportunityApi[] = [
    {
        id: '00000000-0000-4000-8000-000000000301',
        profile_id: EXAMPLE_PROFILE.id,
        run_id: null,
        proposal_id: null,
        kind: 'ai_visibility_gap',
        title: 'What is the best open source session replay tool?',
        score: 1,
        recommended_type: 'new_content',
        target_url: '',
        evidence: [],
        gap: EXAMPLE_GAP,
        status: 'new',
        last_refreshed_at: '2026-08-26T12:00:00Z',
        created_at: '2026-08-26T12:00:00Z',
        updated_at: '2026-08-26T12:00:00Z',
    },
    {
        id: '00000000-0000-4000-8000-000000000302',
        profile_id: EXAMPLE_PROFILE.id,
        run_id: EXAMPLE_RUN.id,
        proposal_id: EXAMPLE_PROPOSAL.id,
        kind: 'ai_visibility_gap',
        title: 'Does web analytics work without cookies?',
        score: 0.64,
        recommended_type: 'page_improvement',
        target_url: 'https://docs.example.com/docs/web-analytics',
        evidence: [],
        gap: { ...EXAMPLE_GAP, cited_checks: 3, mentioned_checks: 6, engines_not_citing: ['exa-answer'] },
        status: 'drafted',
        last_refreshed_at: '2026-08-26T12:00:00Z',
        created_at: '2026-08-26T12:00:00Z',
        updated_at: '2026-08-26T12:00:00Z',
    },
]
