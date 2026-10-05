import { useActions } from 'kea'

import { IconBolt, IconClock, IconStarFilled, IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { WorkflowTemplateCard } from '../Workflows/templates/WorkflowTemplateCard'
import { WorkflowTemplateSteps } from '../Workflows/templates/WorkflowTemplateSteps'
import { firstRunGalleryLogic, GalleryTemplate } from './firstRunGalleryLogic'

export function GalleryTemplateCard({
    galleryTemplate,
    recommendedBecause,
}: {
    galleryTemplate: GalleryTemplate
    recommendedBecause?: string
}): JSX.Element {
    const { pickTemplate } = useActions(firstRunGalleryLogic)
    const { template, ready } = galleryTemplate

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
                    {template.image_url && (
                        <img
                            src={template.image_url}
                            alt=""
                            className="w-full aspect-video max-h-48 object-cover rounded"
                        />
                    )}
                    <WorkflowTemplateSteps actions={template.actions} edges={template.edges} />
                </div>
            }
            footer={
                <div className="flex flex-col gap-1 text-xs">
                    {recommendedBecause && <span className="font-medium">{recommendedBecause}</span>}
                    <StartsOnLine galleryTemplate={galleryTemplate} />
                    {!ready && <StillNeedsLine galleryTemplate={galleryTemplate} />}
                </div>
            }
            onClick={() => pickTemplate(template.id)}
            data-attr={recommendedBecause ? 'first-run-recommended-template' : 'first-run-template'}
        />
    )
}

function StartsOnLine({ galleryTemplate }: { galleryTemplate: GalleryTemplate }): JSX.Element {
    const { startsOn, matchedEvent } = galleryTemplate
    const event = matchedEvent ?? startsOn.events[0]

    if (startsOn.kind === 'schedule') {
        return (
            <span className="flex items-center gap-1 text-accent">
                <IconClock className="shrink-0" />
                {capitalizeFirstLetter(startsOn.detail)}
            </span>
        )
    }
    return (
        <span className="flex flex-wrap items-center gap-1 text-accent">
            {startsOn.kind === 'event' ? <IconBolt className="shrink-0" /> : <IconClock className="shrink-0" />}
            {startsOn.kind === 'no_event' && <span>No</span>}
            <EventChip event={event} />
            {startsOn.detail && <span>{startsOn.detail}</span>}
        </span>
    )
}

function StillNeedsLine({ galleryTemplate }: { galleryTemplate: GalleryTemplate }): JSX.Element {
    const { startsOn } = galleryTemplate
    return (
        <span className="flex flex-wrap items-center gap-1 text-warning">
            <IconWarning className="shrink-0" />
            {startsOn.kind === 'schedule' ? (
                <span>Your app does not send any events yet</span>
            ) : (
                <>
                    <span>Your app does not send</span>
                    <EventChip event={startsOn.events[0]} />
                    <span>yet</span>
                </>
            )}
        </span>
    )
}

function EventChip({ event }: { event: string }): JSX.Element {
    return (
        <LemonTag size="small" className="max-w-full">
            <PropertyKeyInfo value={event} type={TaxonomicFilterGroupType.Events} disablePopover ellipsis />
        </LemonTag>
    )
}
