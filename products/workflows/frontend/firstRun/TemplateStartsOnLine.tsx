import { IconBolt, IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { GalleryTemplate } from './firstRunGalleryLogic'

export function TemplateStartsOnLine({ galleryTemplate }: { galleryTemplate: GalleryTemplate }): JSX.Element {
    const { startsOn, matchedEvent } = galleryTemplate

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
            <EventChip event={matchedEvent ?? startsOn.events[0]} />
            {startsOn.detail && <span>{startsOn.detail}</span>}
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
