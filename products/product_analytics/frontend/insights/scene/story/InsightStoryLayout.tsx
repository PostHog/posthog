import { useValues } from 'kea'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'
import { InsightStoryPanel } from './InsightStoryPanel'

export interface InsightStoryLayoutProps {
    insightProps: InsightLogicProps
    children: React.ReactNode
}

export function InsightStoryLayout({ insightProps, children }: InsightStoryLayoutProps): JSX.Element {
    const { storyOpen } = useValues(insightStoryLogic(insightProps))

    return (
        <div className="@container/story">
            <div className={storyOpen ? 'flex flex-col @3xl/story:flex-row' : undefined}>
                <div className="min-w-0 flex-1">{children}</div>
                {storyOpen && <InsightStoryPanel insightProps={insightProps} />}
            </div>
        </div>
    )
}
