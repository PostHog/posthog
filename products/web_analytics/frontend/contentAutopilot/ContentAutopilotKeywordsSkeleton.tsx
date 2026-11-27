import { Skeleton } from '@posthog/quill'

import { AiVisibilityCard } from './AiVisibilityCard'

/** The keywords layout while it loads, one placeholder per tile, so nothing moves when the keywords arrive. */
export const ContentAutopilotKeywordsSkeleton = (): JSX.Element => (
    <section className="flex flex-col gap-4" data-attr="content-autopilot-keywords-loading">
        <AiVisibilityCard title="How your keywords perform">
            <Skeleton className="h-32 w-full" />
        </AiVisibilityCard>
        <AiVisibilityCard title="What the engines add to your searches">
            <Skeleton className="h-32 w-full" />
        </AiVisibilityCard>
    </section>
)
