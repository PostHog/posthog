import type { Study, StudySummary } from '../types'

import { MOCK_SESSIONS_ROUND_1, MOCK_SESSIONS_ROUND_2 } from './sessions'

/**
 * Full study with all rounds and sessions - used in study detail view
 */
export const MOCK_STUDY: Study = {
    id: '1',
    name: 'Signup flow friction',
    audience_description: 'Marketing managers at B2B SaaS startups',
    research_goal: 'Identify pain points and drop-off reasons in the signup process',
    target_url: 'https://app.posthog.com/signup',
    rounds: [
        {
            id: 'r1',
            study_id: '1',
            round_number: 1,
            session_count: 3,
            notes: null,
            status: 'completed',
            summary:
                '**Key finding:** 2/3 participants struggled to find pricing before signing up. All appreciated Google SSO. Recommendation: Add pricing link to signup page.',
            sessions: MOCK_SESSIONS_ROUND_1,
            created_at: '2024-12-09T10:00:00Z',
        },
        {
            id: 'r2',
            study_id: '1',
            round_number: 2,
            session_count: 3,
            notes: 'Testing with pricing link added to signup page',
            status: 'completed',
            summary:
                '**Key finding:** Pricing visibility improved! 2/3 participants noticed the new link. Free tier details still need work. Overall sentiment improved from Round 1.',
            sessions: MOCK_SESSIONS_ROUND_2,
            created_at: '2024-12-10T14:00:00Z',
        },
    ],
    created_at: '2024-12-09T09:00:00Z',
}

/**
 * Study summaries for the list view
 */
export const MOCK_STUDY_SUMMARIES: StudySummary[] = [
    {
        id: '1',
        name: 'Signup flow friction',
        audience_description: 'Marketing managers at B2B SaaS startups',
        research_goal: 'Identify pain points and drop-off reasons in the signup process',
        target_url: 'https://app.posthog.com/signup',
        rounds_count: 2,
        total_sessions: 6,
        latest_round_status: 'completed',
        created_at: '2024-12-09T10:00:00Z',
    },
    {
        id: '2',
        name: 'Pricing page clarity',
        audience_description: 'CTOs and engineering leads evaluating analytics tools',
        research_goal: 'Evaluate if pricing tiers and value propositions are clear',
        target_url: 'https://posthog.com/pricing',
        rounds_count: 1,
        total_sessions: 3,
        latest_round_status: 'running',
        created_at: '2024-12-09T14:00:00Z',
    },
    {
        id: '3',
        name: 'Onboarding completion',
        audience_description: 'Product managers new to analytics tools',
        research_goal: 'Find where users drop off in the onboarding wizard',
        target_url: 'https://app.posthog.com/onboarding',
        rounds_count: 1,
        total_sessions: 0,
        latest_round_status: 'generating',
        created_at: '2024-12-09T15:00:00Z',
    },
    {
        id: '4',
        name: 'Dashboard first impressions',
        audience_description: 'Data analysts switching from Google Analytics',
        research_goal: 'Understand initial reactions and confusion points',
        target_url: 'https://app.posthog.com/home',
        rounds_count: 0,
        total_sessions: 0,
        latest_round_status: null,
        created_at: '2024-12-09T16:00:00Z',
    },
]
