import { ContentAutopilotTileSkeleton } from './ContentAutopilotTileSkeleton'

/** The keywords layout while it loads, one placeholder per tile, so nothing moves when the keywords arrive. */
export const ContentAutopilotKeywordsSkeleton = (): JSX.Element => (
    <section className="flex flex-col gap-4" data-attr="content-autopilot-keywords-loading">
        <ContentAutopilotTileSkeleton title="How your keywords perform" skeletonClassName="h-32 w-full" />
        <ContentAutopilotTileSkeleton title="What the engines add to your searches" skeletonClassName="h-32 w-full" />
    </section>
)
