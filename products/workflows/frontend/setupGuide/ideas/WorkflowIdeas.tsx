import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { WorkflowIdeaCard } from './WorkflowIdeaCard'
import { workflowIdeasLogic } from './workflowIdeasLogic'

/** Workflows PostHog drafted for this project from its own events, shown until each is used or dismissed. */
export function WorkflowIdeas(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.WORKFLOWS_IDEAS] ? <WorkflowIdeasSection /> : null
}

function WorkflowIdeasSection(): JSX.Element | null {
    const { ideas, ideasLoading } = useValues(workflowIdeasLogic)

    if (ideas === null && ideasLoading) {
        return (
            <div className="grid grid-cols-1 gap-3 @3xl:grid-cols-2 @6xl:grid-cols-3">
                {[0, 1, 2].map((index) => (
                    <LemonSkeleton key={index} className="h-48 rounded" />
                ))}
            </div>
        )
    }
    if (!ideas?.length) {
        return null
    }

    return (
        <section
            // Tints the panel with the Workflows product color, which has no ready-made background token.
            className="@container mb-4 flex flex-col gap-3 rounded-lg border p-4 bg-[color-mix(in_srgb,var(--color-product-workflows-light)_10%,transparent)]"
            data-attr="workflow-ideas"
        >
            <div className="flex items-start gap-2">
                <IconSparkles className="mt-0.5 size-5 text-accent" />
                <div className="flex flex-col">
                    <h3 className="mb-0 text-base font-semibold">Workflows drafted for you</h3>
                    <span className="text-xs text-secondary">
                        Built from events your project already sends. Nothing is sent until you turn a workflow on.
                    </span>
                </div>
            </div>
            <div className="grid grid-cols-1 gap-3 @3xl:grid-cols-2 @6xl:grid-cols-3">
                {ideas.map((idea, index) => (
                    // The list puts the project's best first bet at the top.
                    <WorkflowIdeaCard key={idea.id} idea={idea} recommended={index === 0} />
                ))}
            </div>
        </section>
    )
}
