import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { newWorkflowLogic } from '../Workflows/newWorkflowLogic'
import { WorkflowTemplateBlankPreview } from '../Workflows/templates/WorkflowTemplateBlankPreview'
import { WorkflowTemplateCard } from '../Workflows/templates/WorkflowTemplateCard'
import { firstRunGalleryLogic, GalleryFilter } from './firstRunGalleryLogic'
import { GalleryTemplateCard } from './GalleryTemplateCard'

// Each card keeps at least 20rem and the row fills up, so the column count follows the width the scene gives the gallery.
const GALLERY_GRID = 'grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(20rem,100%),1fr))]'

export function WorkflowsFirstRunGallery(): JSX.Element {
    const { galleryTemplates, readyTemplates, shownTemplates, activeFilter, recommendedStarter, galleryLoadFailed } =
        useValues(firstRunGalleryLogic)
    const { setFilter, loadEmailTemplates } = useActions(firstRunGalleryLogic)
    const { createEmptyWorkflow, showNewWorkflowModal } = useActions(newWorkflowLogic)

    return (
        <div className="flex flex-col gap-4" data-attr="workflows-first-run-gallery">
            <div className="flex flex-col gap-1">
                <h2 className="text-xl font-semibold mb-0">Start with an email template</h2>
                {galleryTemplates !== null && (
                    <p className="mb-0 text-secondary">{gallerySubtitle(readyTemplates.length, activeFilter)}</p>
                )}
            </div>
            {galleryTemplates === null ? (
                galleryLoadFailed ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadEmailTemplates }}>
                        Couldn't load the template gallery. Try again, or use New workflow to start from a blank one.
                    </LemonBanner>
                ) : (
                    <div className={GALLERY_GRID}>
                        {[0, 1, 2].map((index) => (
                            <LemonSkeleton key={index} className="h-80" />
                        ))}
                    </div>
                )
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <LemonSegmentedButton<GalleryFilter>
                            size="small"
                            value={activeFilter}
                            onChange={setFilter}
                            options={[
                                {
                                    value: 'picked',
                                    label: `Picked for your data (${readyTemplates.length})`,
                                    disabledReason:
                                        readyTemplates.length === 0
                                            ? 'Your app does not send the events these templates start on yet'
                                            : undefined,
                                    'data-attr': 'first-run-filter-picked',
                                },
                                {
                                    value: 'all',
                                    label: `All email templates (${galleryTemplates.length})`,
                                    'data-attr': 'first-run-filter-all',
                                },
                            ]}
                        />
                        <Link onClick={showNewWorkflowModal} className="text-sm" data-attr="first-run-all-templates">
                            Browse all workflow templates
                        </Link>
                    </div>
                    <div className={GALLERY_GRID}>
                        {shownTemplates.map((galleryTemplate) => (
                            <GalleryTemplateCard
                                key={galleryTemplate.template.id}
                                galleryTemplate={galleryTemplate}
                                recommendedBecause={
                                    galleryTemplate.template.id === recommendedStarter?.templateId
                                        ? recommendedStarter.reason
                                        : undefined
                                }
                            />
                        ))}
                        <WorkflowTemplateCard
                            name="Start playing"
                            description="A blank workflow. Pick any trigger and add your own steps on the canvas."
                            preview={<WorkflowTemplateBlankPreview />}
                            onClick={createEmptyWorkflow}
                            data-attr="first-run-start-playing"
                        />
                    </div>
                </>
            )}
        </div>
    )
}

function gallerySubtitle(readyCount: number, activeFilter: GalleryFilter): string {
    if (readyCount === 0) {
        return 'Your app does not send the events these templates need yet. Each card says what is missing.'
    }
    return activeFilter === 'picked'
        ? 'These templates work with the events your app sends today. Pick one to make it yours.'
        : 'Templates that work with the events your app sends today come first.'
}
