import { FEATURE_FLAGS, type FeatureFlagKey } from 'lib/constants'

export type LeaderboardSectionId = 'key-metrics' | 'intent-topics' | 'models' | 'protocol' | 'agents' | 'reliability'

// A Record so a new section id fails to compile until it has a title. Key order is page order.
const SECTION_TITLES: Record<LeaderboardSectionId, string> = {
    'key-metrics': 'Key metrics',
    'intent-topics': 'Intent topics',
    models: 'Models',
    protocol: 'Protocol',
    agents: 'What agents do',
    reliability: 'Reliability',
}

export const LEADERBOARD_SECTION_IDS = Object.keys(SECTION_TITLES) as LeaderboardSectionId[]

export const leaderboardSectionTitle = (id: LeaderboardSectionId): string => SECTION_TITLES[id]

export const LEADERBOARD_SECTION_FLAGS: Partial<Record<LeaderboardSectionId, FeatureFlagKey>> = {
    'intent-topics': FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS,
}
