import { useValues } from 'kea'
import { type ReactNode } from 'react'

import { LeaderboardSectionId, leaderboardSectionTitle } from './leaderboardSections'
import { mcpLeaderboardSectionsLogic } from './mcpLeaderboardSectionsLogic'

export function Section({ id, children }: { id: LeaderboardSectionId; children: ReactNode }): JSX.Element | null {
    const { isSectionVisible } = useValues(mcpLeaderboardSectionsLogic)

    if (!isSectionVisible(id)) {
        return null
    }
    return (
        <section className="flex min-w-0 flex-col gap-4" data-quill>
            <h2 className="mb-0 text-xl font-semibold text-primary">{leaderboardSectionTitle(id)}</h2>
            {children}
        </section>
    )
}
