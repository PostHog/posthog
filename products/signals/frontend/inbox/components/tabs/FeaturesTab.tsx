import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus, IconRocket } from '@posthog/icons'
import { LemonButton, LemonCard, LemonModal, LemonSkeleton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { featureCreateLogic } from '../../logics/featureCreateLogic'
import { featureListLogic } from '../../logics/featureListLogic'

function NewFeatureModal(): JSX.Element {
    const { newFeatureModalOpen, descriptionDraft, creating } = useValues(featureCreateLogic)
    const { closeNewFeatureModal, setDescriptionDraft, createFeature } = useActions(featureCreateLogic)

    return (
        <LemonModal
            isOpen={newFeatureModalOpen}
            onClose={closeNewFeatureModal}
            title="New feature"
            description="Describe the feature you want to build. An agent will help you plan how to build and measure it."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeNewFeatureModal}
                        disabledReason={creating ? 'Creating…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createFeature}
                        loading={creating}
                        disabledReason={!descriptionDraft.trim() ? 'Describe the idea first' : undefined}
                    >
                        Start planning
                    </LemonButton>
                </>
            }
        >
            <LemonTextArea
                value={descriptionDraft}
                onChange={setDescriptionDraft}
                minRows={3}
                placeholder="e.g. A burndown chart widget for dashboards, driven by error tracking issues"
                autoFocus
            />
        </LemonModal>
    )
}

export function FeaturesTab(): JSX.Element {
    const { features, featuresLoading } = useValues(featureListLogic)
    const { openNewFeatureModal } = useActions(featureCreateLogic)

    const newFeatureButton = (
        <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={openNewFeatureModal}>
            New feature
        </LemonButton>
    )

    if (featuresLoading && features.length === 0) {
        return (
            <div className="flex flex-col gap-2 p-6">
                <LemonSkeleton className="h-16 rounded" repeat={3} />
            </div>
        )
    }

    if (features.length === 0) {
        return (
            <>
                <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted">
                    <IconRocket className="text-2xl" />
                    <h3 className="mb-0">No features yet</h3>
                    <p className="max-w-md text-sm">
                        Create a feature to plan it with an agent, build it, and keep improving it with PostHog data.
                    </p>
                    {newFeatureButton}
                </div>
                <NewFeatureModal />
            </>
        )
    }

    return (
        <div className="flex flex-col gap-2 p-6">
            <div className="flex items-center justify-end">{newFeatureButton}</div>
            {features.map((feature) => (
                <LemonCard
                    key={feature.id}
                    onClick={() => router.actions.push(urls.inboxReport('features', feature.id))}
                    className="flex flex-col gap-1"
                >
                    <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold">{feature.title || 'Untitled feature'}</span>
                        {feature.is_planning ? (
                            <LemonTag type="warning">Planning</LemonTag>
                        ) : (
                            <LemonTag>{feature.status}</LemonTag>
                        )}
                    </div>
                    {feature.summary && <span className="line-clamp-2 text-sm text-muted">{feature.summary}</span>}
                    <TZLabel time={feature.updated_at} className="text-xs text-muted" />
                </LemonCard>
            ))}
            <NewFeatureModal />
        </div>
    )
}
