import type {
    AEOPromptApi,
    AEOPromptCheckApi,
    AEOPromptStatsApi,
    AEOPromptTopicApi,
    AEOPromptVersionApi,
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
        file_path: 'docs/web-analytics.md',
        title: 'Web analytics',
        description: 'Understand web traffic, behavior, and conversion with privacy-friendly analytics.',
        slug: 'web-analytics',
        frontmatter: [],
        internal_links: [],
        source_notes: [],
    },
    original_markdown: [
        '# Web analytics',
        '',
        'Web analytics shows traffic.',
        '',
        '## Install the snippet',
        '',
        'Add the snippet to every page you want to track.',
        '',
        '## Read the dashboard',
        '',
        'The dashboard shows visitors, page views, and sessions.',
    ].join('\n'),
    proposed_markdown: [
        '# Web analytics',
        '',
        'Web analytics shows traffic, sources, and conversions without cookies.',
        '',
        '## Install the snippet',
        '',
        'Add the snippet to every page you want to track.',
        '',
        '```js',
        "posthog.init('phc_example', { api_host: 'https://us.i.posthog.com' })",
        '```',
        '',
        '## Read the dashboard',
        '',
        'The dashboard shows visitors, page views, and sessions.',
        '',
        '## Frequently asked questions',
    ].join('\n'),
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
    target_url: EXAMPLE_PROPOSAL.target_url,
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

export const EXAMPLE_FAILED_PROPOSAL_LIST: ContentAutopilotProposalListApi = {
    ...EXAMPLE_PROPOSAL_LIST,
    id: '00000000-0000-4000-8000-000000000213',
    lifecycle_status: 'failed',
    title: 'Track AI crawler traffic',
    target_query: 'How do I track AI crawler traffic on my website?',
    file_path: 'docs/web-analytics/ai-crawlers.md',
    target_url: 'https://docs.example.com/docs/web-analytics/ai-crawlers',
    validation_report: {
        ...EXAMPLE_PROPOSAL.validation_report,
        passed: false,
        checks: [
            ...EXAMPLE_PROPOSAL.validation_report.checks,
            {
                check_key: 'grounding',
                label: 'Sourced facts',
                passed: false,
                message: 'These claims aren\'t backed by a source: "Crawler visits never count toward pageviews."',
                blocking: true,
            },
        ],
    },
}

export const EXAMPLE_FAILED_DRAFT_OPPORTUNITY: ContentAutopilotOpportunityApi = {
    ...EXAMPLE_OPPORTUNITIES[0],
    id: '00000000-0000-4000-8000-000000000303',
    proposal_id: EXAMPLE_FAILED_PROPOSAL_LIST.id,
    run_id: EXAMPLE_RUN.id,
    title: 'How do I track AI crawler traffic on my website?',
    status: 'drafted',
}

const EXAMPLE_PROMPT: AEOPromptApi = {
    id: '00000000-0000-4000-8000-000000000301',
    prompt: 'What is the best open source product analytics tool for a small startup?',
    topic: 'Product analytics',
    prompt_source: 'imported',
    rank: 0,
    active: true,
    last_checked_at: '2026-09-29T09:00:00Z',
    external_visibility: 40,
    created_at: '2026-09-01T12:00:00Z',
    updated_at: '2026-09-01T12:00:00Z',
    archived_at: null,
    current_version: 1,
    version_count: 1,
    latest_checks: [
        { engine: 'claude-web-search', cited: true, check_failed: false, checked_at: '2026-09-29T09:00:00Z' },
        { engine: 'openai-web-search', cited: false, check_failed: false, checked_at: '2026-09-29T09:00:00Z' },
        { engine: 'exa-answer', cited: true, check_failed: false, checked_at: '2026-09-29T09:00:00Z' },
    ],
}

export const EXAMPLE_PROMPTS: AEOPromptApi[] = [
    { ...EXAMPLE_PROMPT, current_version: 2, version_count: 2, updated_at: '2026-09-15T12:00:00Z' },
    {
        ...EXAMPLE_PROMPT,
        id: '00000000-0000-4000-8000-000000000302',
        prompt: 'How do I track funnels without writing SQL, and can I break the results down by country and browser?',
        latest_checks: [
            { engine: 'claude-web-search', cited: false, check_failed: false, checked_at: '2026-09-28T09:00:00Z' },
            { engine: 'openai-web-search', cited: false, check_failed: true, checked_at: '2026-09-28T09:00:00Z' },
            { engine: 'gemini-google-search', cited: true, check_failed: false, checked_at: '2026-09-28T09:00:00Z' },
        ],
        last_checked_at: '2026-09-28T09:00:00Z',
    },
    {
        ...EXAMPLE_PROMPT,
        id: '00000000-0000-4000-8000-000000000303',
        prompt: 'Which session replay tools let me mask sensitive inputs by default?',
        topic: 'Session replay',
        active: false,
        latest_checks: [],
        last_checked_at: null,
    },
    {
        ...EXAMPLE_PROMPT,
        id: '00000000-0000-4000-8000-000000000304',
        prompt: 'Is there a free alternative to paid feature flag services?',
        topic: '',
        latest_checks: [
            { engine: 'exa-answer', cited: false, check_failed: false, checked_at: '2026-09-27T09:00:00Z' },
        ],
        last_checked_at: '2026-09-27T09:00:00Z',
    },
    {
        ...EXAMPLE_PROMPT,
        id: '00000000-0000-4000-8000-000000000305',
        prompt: 'What is the cheapest way to run A/B tests on a static site?',
        topic: 'Experiments',
        active: false,
        archived_at: '2026-09-20T12:00:00Z',
        latest_checks: [
            { engine: 'claude-web-search', cited: false, check_failed: false, checked_at: '2026-09-19T09:00:00Z' },
        ],
        last_checked_at: '2026-09-19T09:00:00Z',
    },
]

export const EXAMPLE_PROMPT_VERSIONS: AEOPromptVersionApi[] = [
    {
        version: 2,
        text: EXAMPLE_PROMPT.prompt,
        version_description: 'Name the audience so answers compare tools for startups',
        created_by: { email: 'jane@example.com', name: 'Jane' },
        created_at: '2026-09-15T12:00:00Z',
        is_current: true,
    },
    {
        version: 1,
        text: 'What is the best open source product analytics tool?',
        version_description: '',
        created_by: null,
        created_at: '2026-09-01T12:00:00Z',
        is_current: false,
    },
]

export const EXAMPLE_PROMPT_TOPICS: AEOPromptTopicApi[] = [
    { topic: '', prompts: 1 },
    { topic: 'Product analytics', prompts: 2 },
    { topic: 'Session replay', prompts: 1 },
]

const EXAMPLE_CHECK: AEOPromptCheckApi = {
    id: '00000000-0000-4000-8000-000000000401',
    run_id: '00000000-0000-4000-8000-000000000501',
    engine: 'claude-web-search',
    model: 'example-model-large',
    created_at: '2026-09-29T09:00:00Z',
    cited: true,
    check_failed: false,
    error: null,
    cited_urls: [
        'https://analytics-review.example.com/best-open-source-tools',
        'https://example.com/docs/product-analytics',
        'https://community.example.org/threads/startup-analytics',
    ],
    target_urls: ['https://example.com/docs/product-analytics'],
    target_best_position: 2,
    top_cited_domains: ['analytics-review.example.com', 'example.com', 'community.example.org'],
    search_queries: ['best open source product analytics', 'self-hosted product analytics for startups'],
    prompt_version: 2,
    answer_text:
        'For a small startup, a few open source product analytics tools stand out.\n\n' +
        '1. Example Analytics: event tracking, funnels and retention, with a generous free tier.\n' +
        '2. A self-hosted option if you need to keep data on your own servers.\n\n' +
        'Pick the one that matches how much infrastructure you want to run.',
}

export const EXAMPLE_PROMPT_CHECKS: AEOPromptCheckApi[] = [
    EXAMPLE_CHECK,
    {
        ...EXAMPLE_CHECK,
        id: '00000000-0000-4000-8000-000000000402',
        engine: 'openai-web-search',
        cited: false,
        cited_urls: ['https://analytics-review.example.com/best-open-source-tools'],
        target_urls: [],
        target_best_position: null,
        top_cited_domains: ['analytics-review.example.com'],
        search_queries: ['open source product analytics startup'],
        answer_text: 'Most startups begin with a hosted tool.\nCompare pricing tiers before you commit.',
    },
    {
        ...EXAMPLE_CHECK,
        id: '00000000-0000-4000-8000-000000000403',
        engine: 'exa-answer',
        created_at: '2026-09-28T09:00:00Z',
        cited: false,
        check_failed: true,
        prompt_version: 1,
        error: 'The engine timed out.',
        cited_urls: [],
        target_urls: [],
        target_best_position: null,
        top_cited_domains: [],
        search_queries: [],
        answer_text: null,
    },
]

const EXAMPLE_ENGINE_DAYS: Record<string, ('cited' | 'not_cited' | 'failed' | null)[]> = {
    'claude-web-search': ['cited', 'cited', null, 'not_cited', 'cited', 'cited', 'cited', 'failed', 'cited', 'cited'],
    'openai-web-search': [
        'not_cited',
        'not_cited',
        null,
        'cited',
        'not_cited',
        'not_cited',
        null,
        'not_cited',
        'cited',
        'not_cited',
    ],
    'exa-answer': ['cited', 'failed', null, 'cited', 'cited', 'not_cited', 'cited', 'cited', 'failed', 'cited'],
}

const EXAMPLE_PROMPT_DAILY: AEOPromptStatsApi['daily'] = Object.entries(EXAMPLE_ENGINE_DAYS).flatMap(
    ([engine, pattern]) =>
        Array.from({ length: 29 }, (_, index) => ({ index, status: pattern[index % pattern.length] }))
            .filter(({ status }) => status !== null)
            .map(({ index, status }) => ({
                date: `2026-09-${String(index + 1).padStart(2, '0')}`,
                engine,
                checks: 1,
                cited: status === 'cited' ? 1 : 0,
                failed: status === 'failed' ? 1 : 0,
            }))
)

const exampleEngineStats = (engine: string): AEOPromptStatsApi['engines'][number] => {
    const days = EXAMPLE_PROMPT_DAILY.filter((row) => row.engine === engine)
    const sum = (key: 'checks' | 'cited' | 'failed'): number => days.reduce((total, row) => total + row[key], 0)
    const answered = sum('checks') - sum('failed')
    return {
        engine,
        checks: sum('checks'),
        cited: sum('cited'),
        failed: sum('failed'),
        citation_rate: answered ? sum('cited') / answered : null,
        first_checked_at: `${days[0].date}T09:00:00Z`,
        last_checked_at: `${days[days.length - 1].date}T09:00:00Z`,
    }
}

export const EXAMPLE_PROMPT_STATS: AEOPromptStatsApi = {
    total_checks: EXAMPLE_PROMPT_DAILY.length,
    daily_from: '2026-09-01',
    daily_to: '2026-09-30',
    engines: Object.keys(EXAMPLE_ENGINE_DAYS).map(exampleEngineStats),
    daily: EXAMPLE_PROMPT_DAILY,
}
