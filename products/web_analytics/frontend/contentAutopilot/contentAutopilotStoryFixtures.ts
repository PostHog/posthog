import type {
    AEOBrandApi,
    AEOEngineSettingApi,
    AEOKeywordApi,
    AEOKeywordModifierReportApi,
    AEOKeywordReportApi,
    AEOPromptApi,
    AEOPromptCheckApi,
    AEOPromptCitationApi,
    AEOPromptSetCountsApi,
    AEOPromptSetMoversApi,
    AEOPromptSetOverviewApi,
    AEOPromptSetRankingsApi,
    AEOPromptStatsApi,
    AEOPromptTopicApi,
    AEOPromptVersionApi,
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
    branded: false,
    latest_checks: [
        {
            engine: 'claude-web-search',
            mode: 'web_search',
            cited: true,
            mentioned: true,
            check_failed: false,
            target_best_position: 1,
            search_queries: [
                'best open source product analytics for startups 2026',
                'open source product analytics comparison',
            ],
            checked_at: '2026-09-29T09:00:00Z',
        },
        {
            engine: 'openai-web-search',
            mode: 'web_search',
            cited: false,
            mentioned: false,
            check_failed: false,
            target_best_position: null,
            search_queries: ['best open source product analytics for startups 2026'],
            checked_at: '2026-09-29T09:00:00Z',
        },
        {
            engine: 'exa-answer',
            mode: 'web_search',
            cited: true,
            mentioned: true,
            check_failed: false,
            target_best_position: 3,
            search_queries: [],
            checked_at: '2026-09-29T09:00:00Z',
        },
        {
            engine: 'claude-no-search',
            mode: 'no_search',
            cited: false,
            mentioned: true,
            check_failed: false,
            target_best_position: null,
            search_queries: [],
            checked_at: '2026-09-29T09:00:00Z',
        },
    ],
}

export const EXAMPLE_PROMPTS: AEOPromptApi[] = [
    { ...EXAMPLE_PROMPT, current_version: 2, version_count: 2, updated_at: '2026-09-15T12:00:00Z' },
    {
        ...EXAMPLE_PROMPT,
        id: '00000000-0000-4000-8000-000000000302',
        prompt: 'How do I track funnels without writing SQL, and can I break the results down by country and browser?',
        latest_checks: [
            {
                engine: 'claude-web-search',
                mode: 'web_search',
                cited: false,
                mentioned: false,
                check_failed: false,
                target_best_position: null,
                search_queries: ['funnel analysis without SQL breakdown by country'],
                checked_at: '2026-09-28T09:00:00Z',
            },
            {
                engine: 'openai-web-search',
                mode: 'web_search',
                cited: false,
                mentioned: false,
                check_failed: true,
                target_best_position: null,
                search_queries: [],
                checked_at: '2026-09-28T09:00:00Z',
            },
            {
                engine: 'gemini-google-search',
                mode: 'web_search',
                cited: true,
                mentioned: true,
                check_failed: false,
                target_best_position: 2,
                search_queries: [],
                checked_at: '2026-09-28T09:00:00Z',
            },
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
        prompt: 'Is Example a good free alternative to paid feature flag services?',
        topic: '',
        branded: true,
        latest_checks: [
            {
                engine: 'exa-answer',
                mode: 'web_search',
                cited: false,
                mentioned: false,
                check_failed: false,
                target_best_position: null,
                search_queries: [],
                checked_at: '2026-09-27T09:00:00Z',
            },
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
            {
                engine: 'claude-web-search',
                mode: 'web_search',
                cited: false,
                mentioned: false,
                check_failed: false,
                target_best_position: null,
                search_queries: [],
                checked_at: '2026-09-19T09:00:00Z',
            },
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

const EXAMPLE_SCORED_SENTENCES = [
    {
        sentence: '1. Example Analytics: event tracking, funnels and retention, with a generous free tier.',
        label: 'positive',
        score: 0.91,
    },
    { sentence: 'Example Analytics gets expensive at high event volumes.', label: 'negative', score: 0.78 },
]

const EXAMPLE_ANSWER_TEXT =
    'For a small startup, a few open source product analytics tools stand out.\n\n' +
    `${EXAMPLE_SCORED_SENTENCES[0].sentence}\n` +
    '2. Rival Analytics, if you mostly need dashboards and can live with a smaller free tier.\n' +
    '3. A self-hosted option if you need to keep data on your own servers.\n\n' +
    `${EXAMPLE_SCORED_SENTENCES[1].sentence} Pick the one that matches how much infrastructure you want to run.`

const EXAMPLE_CHECK: AEOPromptCheckApi = {
    id: '00000000-0000-4000-8000-000000000401',
    run_id: '00000000-0000-4000-8000-000000000501',
    engine: 'claude-web-search',
    mode: 'web_search',
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
    brand_sentiment: 'positive',
    brand_sentiment_score: 0.86,
    brand_sentiment_sentences: EXAMPLE_SCORED_SENTENCES.map(({ sentence, label, score }) => ({
        start: EXAMPLE_ANSWER_TEXT.indexOf(sentence),
        end: EXAMPLE_ANSWER_TEXT.indexOf(sentence) + sentence.length,
        label,
        score,
    })),
    answer_text: EXAMPLE_ANSWER_TEXT,
}

export const EXAMPLE_COMPETITOR_BRANDS: AEOBrandApi[] = [
    {
        id: '0193a6f1-0000-0000-0000-000000000001',
        name: 'Rival Analytics',
        domain: 'rival.example.org',
        kind: 'competitor',
        status: 'confirmed',
        source: 'manual',
        aliases: ['Rival'],
        created_at: '2026-09-01T00:00:00Z',
        updated_at: null,
    },
]

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
        brand_sentiment: null,
        brand_sentiment_score: null,
        brand_sentiment_sentences: [],
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
        brand_sentiment: null,
        brand_sentiment_score: null,
        brand_sentiment_sentences: [],
        answer_text: null,
    },
]

export const EXAMPLE_PROMPT_CITATIONS: AEOPromptCitationApi[] = [
    {
        ...EXAMPLE_CHECK,
        prompt_id: EXAMPLE_PROMPTS[0].id,
        prompt_text: EXAMPLE_PROMPTS[0].prompt,
        prompt_topic: EXAMPLE_PROMPTS[0].topic,
        mentioned: true,
    },
    {
        ...EXAMPLE_PROMPT_CHECKS[1],
        prompt_id: EXAMPLE_PROMPTS[1].id,
        prompt_text: EXAMPLE_PROMPTS[1].prompt,
        prompt_topic: EXAMPLE_PROMPTS[1].topic,
        mentioned: false,
    },
    {
        ...EXAMPLE_PROMPT_CHECKS[1],
        id: '00000000-0000-4000-8000-000000000404',
        engine: 'exa-answer',
        created_at: '2026-09-27T09:00:00Z',
        answer_text: 'Example Analytics and Rival Analytics both have free tiers.',
        prompt_id: EXAMPLE_PROMPTS[1].id,
        prompt_text: EXAMPLE_PROMPTS[1].prompt,
        prompt_topic: EXAMPLE_PROMPTS[1].topic,
        mentioned: true,
    },
]

type ExampleDay = 'cited' | 'mentioned' | 'not_cited' | 'failed' | null

const EXAMPLE_ENGINE_DAYS: Record<string, ExampleDay[]> = {
    'claude-web-search': ['cited', 'cited', null, 'mentioned', 'cited', 'cited', 'cited', 'failed', 'cited', 'cited'],
    'openai-web-search': [
        'not_cited',
        'mentioned',
        null,
        'cited',
        'not_cited',
        'mentioned',
        null,
        'not_cited',
        'cited',
        'mentioned',
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
                mentioned: status === 'cited' || status === 'mentioned' ? 1 : 0,
                failed: status === 'failed' ? 1 : 0,
                avg_position: status === 'cited' ? (index % 3) + 1 : null,
            }))
)

const exampleEngineStats = (engine: string): AEOPromptStatsApi['engines'][number] => {
    const days = EXAMPLE_PROMPT_DAILY.filter((row) => row.engine === engine)
    const sum = (key: 'checks' | 'cited' | 'mentioned' | 'failed'): number =>
        days.reduce((total, row) => total + row[key], 0)
    const answered = sum('checks') - sum('failed')
    return {
        engine,
        checks: sum('checks'),
        cited: sum('cited'),
        mentioned: sum('mentioned'),
        failed: sum('failed'),
        avg_position: sum('cited')
            ? days.reduce((total, row) => total + (row.avg_position ?? 0) * row.cited, 0) / sum('cited')
            : null,
        citation_rate: answered ? sum('cited') / answered : null,
        mention_rate: answered ? sum('mentioned') / answered : null,
        first_checked_at: `${days[0].date}T09:00:00Z`,
        last_checked_at: `${days[days.length - 1].date}T09:00:00Z`,
    }
}

const EXAMPLE_CONSENSUS_DOMAINS = [
    'analytics-review.example.com',
    'example.com',
    'community.example.org',
    'rival.example.net',
    'docs.rival.example.net',
]

export const EXAMPLE_PROMPT_STATS: AEOPromptStatsApi = {
    total_checks: EXAMPLE_PROMPT_DAILY.length,
    brand_names: ['example'],
    daily_from: '2026-09-01',
    daily_to: '2026-09-30',
    engines: Object.keys(EXAMPLE_ENGINE_DAYS).map(exampleEngineStats),
    daily: EXAMPLE_PROMPT_DAILY,
    consensus: Object.keys(EXAMPLE_ENGINE_DAYS).flatMap((engine, engineIndex) =>
        EXAMPLE_CONSENSUS_DOMAINS.map((domain, domainIndex) => ({
            engine,
            domain,
            checks: 24,
            checks_citing: Math.max(0, 22 - domainIndex * 5 - engineIndex * 3),
        }))
    ),
    sentiment: [
        { engine: 'claude-web-search', positive: 14, neutral: 6, negative: 1, unscored: 2 },
        { engine: 'openai-web-search', positive: 5, neutral: 9, negative: 3, unscored: 0 },
        { engine: 'exa-answer', positive: 0, neutral: 0, negative: 0, unscored: 18 },
    ],
    top_words: [
        { word: 'analytics', count: 41 },
        { word: 'product', count: 38 },
        { word: 'open', count: 22 },
        { word: 'source', count: 22 },
        { word: 'startups', count: 11 },
    ],
}

const setCounts = (
    counts: Pick<AEOPromptSetCountsApi, 'checks' | 'failed' | 'cited' | 'mentioned' | 'prompts' | 'prompts_cited'>,
    avgPosition: number | null = null
): AEOPromptSetCountsApi => {
    const answered = counts.checks - counts.failed
    return {
        ...counts,
        avg_position: counts.cited ? avgPosition : null,
        citation_rate: answered ? counts.cited / answered : null,
        mention_rate: answered ? counts.mentioned / answered : null,
    }
}

// 30 answers per engine per day, with rates that drift around each engine's level so the lines read apart.
const OVERVIEW_ENGINE_LEVELS: [engine: string, cited: number, mentioned: number][] = [
    ['claude-web-search', 0.5, 0.7],
    ['exa-answer', 0.2, 0.4],
    ['openai-web-search', 0.46, 0.66],
]

const EXAMPLE_PROMPT_SET_DAILY: AEOPromptSetOverviewApi['daily'] = Array.from({ length: 30 }, (_, index) =>
    OVERVIEW_ENGINE_LEVELS.map(([engine, cited, mentioned], engineIndex) => {
        const drift = Math.sin(index / 4 + engineIndex) * 0.06
        return {
            date: `2026-09-${String(index + 1).padStart(2, '0')}`,
            engine,
            checks: 30,
            failed: 0,
            cited: Math.round((cited + drift) * 30),
            mentioned: Math.round((mentioned + drift) * 30),
            avg_position: Math.round((2.3 + engineIndex * 0.4 - drift * 5) * 10) / 10,
        }
    })
).flat()

// Answered checks per engine and topic. One engine has no answer about experiments, and no engine has one about
// surveys, so the grid shows empty cells next to a rate of zero.
const OVERVIEW_ENGINE_TOPICS: [engine: string, topic: string, answers: number, mentioned: number][] = [
    ['claude-web-search', '', 20, 6],
    ['claude-web-search', 'Experiments', 180, 104],
    ['claude-web-search', 'Feature flags', 170, 140],
    ['claude-web-search', 'Product analytics', 320, 283],
    ['claude-web-search', 'Session replay', 200, 90],
    ['exa-answer', '', 20, 0],
    ['exa-answer', 'Feature flags', 130, 49],
    ['exa-answer', 'Product analytics', 250, 151],
    ['exa-answer', 'Session replay', 300, 80],
    ['openai-web-search', '', 20, 6],
    ['openai-web-search', 'Experiments', 170, 36],
    ['openai-web-search', 'Feature flags', 170, 140],
    ['openai-web-search', 'Product analytics', 310, 270],
    ['openai-web-search', 'Session replay', 200, 121],
]

export const EXAMPLE_PROMPT_SET_OVERVIEW: AEOPromptSetOverviewApi = {
    days: 30,
    window_from: '2026-09-01',
    window_to: '2026-09-30',
    prompts_tracked: 42,
    target_domains: ['example.com'],
    brand_names: ['example'],
    branded: 'non_branded',
    engine: null,
    topic: null,
    branded_answers: 520,
    non_branded_answers: 2460,
    current: setCounts({ checks: 2520, failed: 60, cited: 984, mentioned: 1476, prompts: 44, prompts_cited: 31 }, 2.3),
    previous: setCounts({ checks: 2400, failed: 40, cited: 826, mentioned: 1416, prompts: 40, prompts_cited: 27 }, 2.8),
    engines: [
        {
            engine: 'claude-web-search',
            ...setCounts({ checks: 900, failed: 10, cited: 445, mentioned: 623, prompts: 44, prompts_cited: 30 }, 2.1),
        },
        {
            engine: 'exa-answer',
            ...setCounts({ checks: 720, failed: 20, cited: 140, mentioned: 280, prompts: 44, prompts_cited: 18 }, 3.4),
        },
        {
            engine: 'openai-web-search',
            ...setCounts({ checks: 900, failed: 30, cited: 399, mentioned: 573, prompts: 44, prompts_cited: 28 }, 2.2),
        },
    ],
    daily: EXAMPLE_PROMPT_SET_DAILY,
    topics: [
        {
            topic: '',
            active_prompts: 1,
            ...setCounts({ checks: 60, failed: 0, cited: 6, mentioned: 12, prompts: 1, prompts_cited: 1 }),
        },
        {
            topic: 'Experiments',
            active_prompts: 6,
            ...setCounts({ checks: 360, failed: 10, cited: 70, mentioned: 140, prompts: 6, prompts_cited: 3 }),
        },
        {
            topic: 'Feature flags',
            active_prompts: 8,
            ...setCounts({ checks: 480, failed: 10, cited: 188, mentioned: 329, prompts: 8, prompts_cited: 7 }),
        },
        {
            topic: 'Product analytics',
            active_prompts: 15,
            ...setCounts({ checks: 900, failed: 20, cited: 528, mentioned: 704, prompts: 16, prompts_cited: 14 }),
        },
        {
            topic: 'Session replay',
            active_prompts: 12,
            ...setCounts({ checks: 720, failed: 20, cited: 192, mentioned: 291, prompts: 13, prompts_cited: 6 }),
        },
        {
            topic: 'Surveys',
            active_prompts: 2,
            ...setCounts({ checks: 0, failed: 0, cited: 0, mentioned: 0, prompts: 0, prompts_cited: 0 }),
        },
    ],
    engine_topics: OVERVIEW_ENGINE_TOPICS.map(([engine, topic, answers, mentioned]) => ({
        engine,
        topic,
        answers,
        mentioned,
        mention_rate: mentioned / answers,
    })),
    top_domains: [
        { domain: 'analytics-review.example.com', answers: 1180, share_of_answers: 0.48, is_target: false },
        { domain: 'example.com', answers: 984, share_of_answers: 0.4, is_target: true },
        { domain: 'community.example.org', answers: 590, share_of_answers: 0.24, is_target: false },
    ],
    top_searches: [
        {
            query: 'open source product analytics',
            prompts: 9,
            answers: 214,
            cited: 131,
            engines: ['claude-web-search', 'exa-answer', 'openai-web-search'],
            top_prompts: [
                {
                    id: '00000000-0000-4000-8000-000000000301',
                    text: 'What is the best open source product analytics tool for a small startup?',
                },
                {
                    id: '00000000-0000-4000-8000-000000000302',
                    text: 'How do I track funnels without writing SQL, and can I break the results down by country and browser?',
                },
            ],
        },
        {
            query: 'session replay mask inputs',
            prompts: 4,
            answers: 88,
            cited: 12,
            engines: ['claude-web-search', 'openai-web-search'],
            top_prompts: [
                {
                    id: '00000000-0000-4000-8000-000000000303',
                    text: 'Which session replay tools let me mask sensitive inputs by default?',
                },
            ],
        },
        {
            query: 'free feature flag service',
            prompts: 3,
            answers: 61,
            cited: 0,
            engines: ['exa-answer'],
            top_prompts: [
                {
                    id: '00000000-0000-4000-8000-000000000304',
                    text: 'Is there a free alternative to paid feature flag services?',
                },
            ],
        },
    ],
}

const RANKED_BRANDS: AEOPromptSetRankingsApi['brands'] = [
    {
        domain: 'example.com',
        name: 'example',
        is_target: true,
        answers_mentioning: 1012,
        visibility: 0.41,
        previous_visibility: 0.371,
        positive_share: 0.82,
    },
    {
        domain: 'rival.example.org',
        name: 'rival',
        is_target: false,
        answers_mentioning: 457,
        visibility: 0.185,
        previous_visibility: 0.158,
        positive_share: null,
    },
    {
        domain: 'metrics.example.net',
        name: 'metrics',
        is_target: false,
        answers_mentioning: 425,
        visibility: 0.172,
        previous_visibility: 0.154,
        positive_share: null,
    },
    {
        domain: 'flagship.example.io',
        name: 'flagship',
        is_target: false,
        answers_mentioning: 306,
        visibility: 0.124,
        previous_visibility: 0.141,
        positive_share: null,
    },
]

// Thirty days ending on the mocked date, each brand wobbling around its window visibility.
const RANKED_DAYS = Array.from({ length: 30 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 8, 1 + index))
    return date.toISOString().slice(0, 10)
})

export const EXAMPLE_PROMPT_SET_RANKINGS: AEOPromptSetRankingsApi = {
    days: 30,
    window_from: RANKED_DAYS[0],
    window_to: RANKED_DAYS[RANKED_DAYS.length - 1],
    branded: 'non_branded',
    engine: null,
    topic: null,
    answers: 2468,
    competitors_confirmed: false,
    brands: RANKED_BRANDS,
    daily: RANKED_DAYS.flatMap((date, index) =>
        RANKED_BRANDS.map((brand, brandIndex) => ({
            date,
            domain: brand.domain,
            answers: 82,
            visibility: Math.round(((brand.visibility ?? 0) + Math.sin(index / 3 + brandIndex) * 0.02) * 1000) / 1000,
        }))
    ),
    top_domains: [
        {
            domain: 'example.com',
            answers: 509,
            share_of_answers: 0.206,
            urls: 131,
            is_target: true,
            is_competitor: false,
        },
        {
            domain: 'forum.example.org',
            answers: 294,
            share_of_answers: 0.119,
            urls: 287,
            is_target: false,
            is_competitor: false,
        },
        {
            domain: 'rival.example.org',
            answers: 220,
            share_of_answers: 0.089,
            urls: 82,
            is_target: false,
            is_competitor: true,
        },
    ],
    top_pages: [
        { url: 'https://example.com/', answers: 106, share_of_answers: 0.043, is_target: true },
        {
            url: 'https://forum.example.org/best-session-replay-tools',
            answers: 68,
            share_of_answers: 0.028,
            is_target: false,
        },
        { url: 'https://example.com/pricing', answers: 47, share_of_answers: 0.019, is_target: true },
    ],
}

export const EXAMPLE_PROMPT_SET_MOVERS: AEOPromptSetMoversApi = {
    days: 30,
    window_from: RANKED_DAYS[0],
    window_to: RANKED_DAYS[RANKED_DAYS.length - 1],
    branded: 'non_branded',
    engine: null,
    topic: null,
    answers: 2468,
    previous_answers: 2390,
    min_answers: 3,
    prompt_gainers: [
        {
            prompt_id: EXAMPLE_PROMPTS[0].id,
            prompt: EXAMPLE_PROMPTS[0].prompt,
            topic: EXAMPLE_PROMPTS[0].topic,
            answers: 28,
            mentioned: 21,
            mention_rate: 0.75,
            previous_answers: 30,
            previous_mentioned: 9,
            previous_mention_rate: 0.3,
            change: 0.45,
        },
        {
            prompt_id: '00000000-0000-4000-8000-000000000311',
            prompt: 'Which product analytics tools have a free plan?',
            topic: 'Product analytics',
            answers: 30,
            mentioned: 12,
            mention_rate: 0.4,
            previous_answers: 30,
            previous_mentioned: 9,
            previous_mention_rate: 0.3,
            change: 0.1,
        },
    ],
    prompt_losers: [
        {
            prompt_id: EXAMPLE_PROMPTS[1].id,
            prompt: EXAMPLE_PROMPTS[1].prompt,
            topic: 'Product analytics',
            answers: 30,
            mentioned: 6,
            mention_rate: 0.2,
            previous_answers: 29,
            previous_mentioned: 16,
            previous_mention_rate: 0.552,
            change: -0.352,
        },
    ],
    page_gainers: [
        {
            url: 'https://example.com/docs/session-replay/installation',
            answers_citing: 74,
            citation_rate: 0.03,
            previous_answers_citing: 31,
            previous_citation_rate: 0.013,
            change: 0.017,
        },
        {
            url: 'https://example.com/pricing',
            answers_citing: 47,
            citation_rate: 0.019,
            previous_answers_citing: 45,
            previous_citation_rate: 0.0188,
            change: 0.0002,
        },
    ],
    page_losers: [
        {
            url: 'https://example.com/blog/best-open-source-analytics-tools',
            answers_citing: 0,
            citation_rate: 0,
            previous_answers_citing: 52,
            previous_citation_rate: 0.022,
            change: -0.022,
        },
        {
            url: 'https://example.com/',
            answers_citing: 106,
            citation_rate: 0.043,
            previous_answers_citing: 122,
            previous_citation_rate: 0.051,
            change: -0.008,
        },
    ],
}

export const EXAMPLE_KEYWORDS: AEOKeywordApi[] = [
    'feature flags',
    'pricing',
    'self-hosted',
    'session replay',
    'web analytics',
].map((keyword, index) => ({
    id: `00000000-0000-4000-8000-00000000090${index}`,
    keyword,
    created_at: '2026-09-20T12:00:00Z',
}))

export const EXAMPLE_KEYWORD_REPORT: AEOKeywordReportApi = {
    days: 7,
    window_from: '2026-09-24',
    window_to: '2026-09-30',
    answers: 420,
    brand_names: ['example'],
    keywords: [
        {
            keyword: 'feature flags',
            prompts: 6,
            prompt_checks: 84,
            prompt_mention_rate: 0.71,
            prompt_cited_rate: 0.48,
            searched_checks: 61,
            searched_rate: 0.145,
            searched_cited_rate: 0.52,
            answer_checks: 102,
            answer_rate: 0.243,
            uses_per_answer: 3.4,
            answer_mention_rate: 0.66,
            avg_citation_position: 2.3,
            median_first_mention_depth: 0.18,
        },
        {
            keyword: 'pricing',
            prompts: 3,
            prompt_checks: 42,
            prompt_mention_rate: 0.38,
            prompt_cited_rate: 0.14,
            searched_checks: 133,
            searched_rate: 0.317,
            searched_cited_rate: 0.11,
            answer_checks: 190,
            answer_rate: 0.452,
            uses_per_answer: 1.6,
            answer_mention_rate: 0.29,
            avg_citation_position: 4.1,
            median_first_mention_depth: 0.62,
        },
        {
            keyword: 'self-hosted',
            prompts: 0,
            prompt_checks: 0,
            prompt_mention_rate: null,
            prompt_cited_rate: null,
            searched_checks: 38,
            searched_rate: 0.09,
            searched_cited_rate: 0.24,
            answer_checks: 57,
            answer_rate: 0.136,
            uses_per_answer: 1.2,
            answer_mention_rate: 0.47,
            avg_citation_position: 3.0,
            median_first_mention_depth: 0.41,
        },
        {
            keyword: 'session replay',
            prompts: 9,
            prompt_checks: 126,
            prompt_mention_rate: 0.83,
            prompt_cited_rate: 0.61,
            searched_checks: 97,
            searched_rate: 0.231,
            searched_cited_rate: 0.58,
            answer_checks: 151,
            answer_rate: 0.36,
            uses_per_answer: 4.2,
            answer_mention_rate: 0.79,
            avg_citation_position: 1.8,
            median_first_mention_depth: 0.09,
        },
        {
            keyword: 'web analytics',
            prompts: 4,
            prompt_checks: 56,
            prompt_mention_rate: 0.55,
            prompt_cited_rate: 0.3,
            searched_checks: 0,
            searched_rate: 0,
            searched_cited_rate: null,
            answer_checks: 0,
            answer_rate: 0,
            uses_per_answer: null,
            answer_mention_rate: null,
            avg_citation_position: null,
            median_first_mention_depth: null,
        },
    ],
}

export const EXAMPLE_KEYWORD_MODIFIERS: AEOKeywordModifierReportApi = {
    days: 7,
    window_from: '2026-09-24',
    window_to: '2026-09-30',
    keyword: null,
    answers: 420,
    baseline_cited_rate: 0.42,
    modifiers: [
        {
            term: '2026',
            kind: 'freshness',
            answers: 118,
            share: 0.281,
            cited_rate: 0.19,
            engines: [
                { engine: 'openai-web-search', answers: 81 },
                { engine: 'claude-web-search', answers: 37 },
            ],
            example_searches: ['best session replay tools 2026', 'feature flag platforms 2026 comparison'],
        },
        {
            term: 'pricing',
            kind: 'pricing',
            answers: 96,
            share: 0.229,
            cited_rate: 0.22,
            engines: [
                { engine: 'openai-web-search', answers: 60 },
                { engine: 'claude-web-search', answers: 36 },
            ],
            example_searches: ['acme analytics pricing', 'session replay pricing per session'],
        },
        {
            term: 'alternatives',
            kind: 'comparison',
            answers: 74,
            share: 0.176,
            cited_rate: 0.45,
            engines: [{ engine: 'openai-web-search', answers: 74 }],
            example_searches: ['acme alternatives open source', 'web analytics alternatives'],
        },
        {
            term: 'vs acme',
            kind: 'comparison',
            answers: 31,
            share: 0.074,
            cited_rate: 0.39,
            engines: [{ engine: 'claude-web-search', answers: 31 }],
            example_searches: ['example vs acme feature flags'],
        },
        {
            term: 'acme',
            kind: 'competitor',
            answers: 52,
            share: 0.124,
            cited_rate: 0.27,
            engines: [
                { engine: 'openai-web-search', answers: 40 },
                { engine: 'claude-web-search', answers: 12 },
            ],
            example_searches: ['acme session replay review'],
        },
        {
            term: 'official docs',
            kind: 'docs',
            answers: 40,
            share: 0.095,
            cited_rate: 0.63,
            engines: [{ engine: 'claude-web-search', answers: 40 }],
            example_searches: ['feature flags official docs'],
        },
        {
            term: 'site:example.com',
            kind: 'site',
            answers: 22,
            share: 0.052,
            cited_rate: 0.86,
            engines: [{ engine: 'claude-web-search', answers: 22 }],
            example_searches: ['site:example.com session replay privacy'],
        },
        {
            term: 'self hosted',
            kind: 'other',
            answers: 35,
            share: 0.083,
            cited_rate: 0.2,
            engines: [{ engine: 'openai-web-search', answers: 35 }],
            example_searches: ['self hosted product analytics docker'],
        },
    ],
}

export const EXAMPLE_ENGINE_SETTINGS: AEOEngineSettingApi[] = [
    { engine: 'claude-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
    { engine: 'openai-web-search', mode: 'web_search', available: true, enabled: true, frequency: 'daily' },
    { engine: 'perplexity-web-search', mode: 'web_search', available: false, enabled: true, frequency: 'daily' },
    { engine: 'exa-answer', mode: 'web_search', available: true, enabled: false, frequency: 'daily' },
    { engine: 'claude-no-search', mode: 'no_search', available: true, enabled: true, frequency: 'weekly' },
    { engine: 'openai-no-search', mode: 'no_search', available: true, enabled: false, frequency: 'daily' },
]

// Rows the overview's two HogQL tiles read. Rates follow a fixed pattern, so every render draws the same chart.
const CITATION_ENGINES = ['ChatGPT', 'Claude', 'Exa']
const CITATION_DAYS = Array.from({ length: 30 }, (_, index) => `2026-09-${String(index + 1).padStart(2, '0')}`)

export const EXAMPLE_PROMPT_SET_CITATION_RESPONSE = {
    columns: ['day', 'engine_name', 'rate'],
    types: [
        ['day', 'Date'],
        ['engine_name', 'String'],
        ['rate', 'Float64'],
    ],
    results: CITATION_DAYS.flatMap((day, dayIndex) =>
        CITATION_ENGINES.map((engine, engineIndex) => [
            day,
            engine,
            Math.round((0.3 + engineIndex * 0.08 + ((dayIndex * (engineIndex + 2)) % 7) * 0.015) * 1000) / 1000,
        ])
    ),
}

export const EXAMPLE_PROMPT_SET_SOURCES_RESPONSE = {
    columns: ['domain', 'answers', 'share_of_answers', 'is_target'],
    types: [
        ['domain', 'String'],
        ['answers', 'UInt64'],
        ['share_of_answers', 'Float64'],
        ['is_target', 'UInt8'],
    ],
    results: [
        ['analytics-review.example.com', 1180, 0.48, 0],
        ['example.com', 984, 0.4, 1],
        ['community.example.org', 590, 0.24, 0],
        ['docs.example.net', 402, 0.163, 0],
        ['news.example.io', 233, 0.095, 0],
    ],
}
