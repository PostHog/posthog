export type LeaderboardSectionId = 'key-metrics' | 'agent-feedback' | 'usage' | 'agents'

// A Record so a new section id fails to compile until it has a title.
const SECTION_TITLES: Record<LeaderboardSectionId, string> = {
    'key-metrics': 'Key metrics',
    'agent-feedback': 'Missing capabilities',
    usage: 'Usage',
    agents: 'What agents do',
}

export const leaderboardSectionTitle = (id: LeaderboardSectionId): string => SECTION_TITLES[id]
