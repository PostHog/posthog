import { useActions } from 'kea'

import { IconStarFilled, IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { WorkflowTemplateCard } from '../Workflows/templates/WorkflowTemplateCard'
import { WorkflowTemplateSteps } from '../Workflows/templates/WorkflowTemplateSteps'
import { firstRunGalleryLogic, GalleryTemplate } from './firstRunGalleryLogic'
import { TemplateStartsOnLine } from './TemplateStartsOnLine'

export function GalleryTemplateCard({
    galleryTemplate,
    recommendedBecause,
}: {
    galleryTemplate: GalleryTemplate
    recommendedBecause?: string
}): JSX.Element {
    const { pickTemplate } = useActions(firstRunGalleryLogic)
    const { template, startsOn, ready } = galleryTemplate

    return (
        <WorkflowTemplateCard
            name={template.name || 'Unnamed template'}
            description={template.description}
            highlighted={!!recommendedBecause}
            badge={
                recommendedBecause ? (
                    <LemonTag type="highlight" icon={<IconStarFilled />} className="shrink-0">
                        Recommended starter
                    </LemonTag>
                ) : null
            }
            preview={
                <div className="flex flex-col gap-3 w-full">
                    {recommendedBecause && <span className="text-sm font-medium">{recommendedBecause}</span>}
                    {template.image_url && (
                        <img
                            src={template.image_url}
                            alt=""
                            loading="lazy"
                            className="w-full aspect-video max-h-48 object-cover rounded"
                        />
                    )}
                    <WorkflowTemplateSteps actions={template.actions} edges={template.edges} />
                </div>
            }
            footer={
                <div className="flex flex-col gap-1 text-xs">
                    <TemplateStartsOnLine galleryTemplate={galleryTemplate} />
                    {!ready && (
                        <span className="flex items-center gap-1 text-warning">
                            <IconWarning className="shrink-0" />
                            {startsOn.kind === 'schedule'
                                ? 'Your app does not send any events yet'
                                : 'Your app does not send this event yet'}
                        </span>
                    )}
                </div>
            }
            onClick={() => pickTemplate(template.id)}
            data-attr={recommendedBecause ? 'first-run-recommended-template' : 'first-run-template'}
        />
    )
}
