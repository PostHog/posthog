// ============================================
// Status Types
// ============================================
export type StudyStatus = 'draft' | 'generating' | 'running' | 'completed' | 'failed'
export type RoundStatus = 'draft' | 'generating' | 'ready' | 'running' | 'completed' | 'failed'
export type ParticipantStatus = 'pending' | 'generating' | 'navigating' | 'completed' | 'failed'
export type Sentiment = 'positive' | 'neutral' | 'negative'

// ============================================
// Core Entities
// ============================================

/**
 * A session represents a single synthetic user navigating the target URL.
 * Each session has a generated persona, a plan, and captures their experience.
 */
export interface Session {
    id: string
    round_id: string
    // Generated persona
    name: string
    archetype: string
    background: string
    traits: string[]
    // Generated plan based on persona + research goal
    plan: string
    // Execution
    status: ParticipantStatus
    session_replay_url: string | null
    // Stream of consciousness - simple list of thoughts
    thought_action_log: string[]
    // Results
    experience_writeup: string | null
    key_insights: string[]
    sentiment: Sentiment | null
    created_at: string
}

/**
 * A round is a single execution of a study with N sessions.
 * Multiple rounds allow iterating on changes and comparing results.
 */
export interface Round {
    id: string
    study_id: string
    round_number: number
    session_count: number
    notes: string | null // what changed since last round
    status: RoundStatus
    summary: string | null
    sessions?: Session[] // optional until sessions are implemented
    created_at: string
}

/**
 * A study defines the research goal and target audience.
 * It contains multiple rounds, each with their own sessions.
 */
export interface Study {
    id: string
    name: string
    audience_description: string // "Marketing managers at B2B SaaS startups"
    research_goal: string // "Identify pain points in the signup flow"
    target_url: string // URL to test
    rounds?: Round[] // optional, included when fetching single study
    created_at: string
}

/**
 * Summary view of a study for the list page.
 */
export interface StudySummary {
    id: string
    name: string
    audience_description: string
    research_goal: string
    target_url: string
    rounds_count: number
    total_sessions: number
    latest_round_status: RoundStatus | null
    created_at: string
}

/**
 * Form values for creating/editing a study.
 */
export interface StudyFormValues {
    name: string
    audience_description: string
    research_goal: string
    target_url: string
}

/**
 * Form values for creating a round.
 */
export interface RoundFormValues {
    session_count: number
    notes: string
}
