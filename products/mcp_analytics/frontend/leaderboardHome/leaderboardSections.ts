export type LeaderboardSectionId = 'key-metrics' | 'models' | 'protocol' | 'agents' | 'reliability'

// A Record so a new section id fails to compile until it has a title. Key order is page order.
const SECTION_TITLES: Record<LeaderboardSectionId, string> = {
    'key-metrics': 'Key metrics',
    models: 'Models',
    protocol: 'Protocol',
    agents: 'What agents do',
    reliability: 'Reliability',
}

export const LEADERBOARD_SECTION_IDS = Object.keys(SECTION_TITLES) as LeaderboardSectionId[]

export const leaderboardSectionTitle = (id: LeaderboardSectionId): string => SECTION_TITLES[id]
