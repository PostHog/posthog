import { IconBolt, IconClock } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, Text, cn } from '@posthog/quill'

import { SpaceLoopTemplate, SpaceLoopTemplateTone } from './spaceLoopTemplateCatalog'

const TONE_CLASSES: Record<SpaceLoopTemplateTone, string> = {
    info: 'text-info-foreground',
    destructive: 'text-destructive-foreground',
    completed: 'text-completed-foreground',
    success: 'text-success-foreground',
    warning: 'text-warning-foreground',
}

export function SpaceLoopTemplateCard({
    template,
    onSelect,
}: {
    template: SpaceLoopTemplate
    onSelect: () => void
}): JSX.Element {
    const { Icon } = template
    const TriggerIcon = template.triggerLabel.startsWith('Triggered') ? IconBolt : IconClock

    return (
        <Item
            variant="outline"
            size="sm"
            render={<button type="button" onClick={onSelect} />}
            className="h-full items-start text-left transition-colors hover:bg-fill-hover"
            data-attr="today-space-loop-template"
        >
            <ItemMedia variant="icon" className={cn(TONE_CLASSES[template.tone])}>
                <Icon />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle>{template.name}</ItemTitle>
                <ItemDescription className="line-clamp-none">{template.description}</ItemDescription>
                <span className="mt-0.5 flex items-center gap-1 text-muted-foreground">
                    <TriggerIcon className="size-3 shrink-0" />
                    <Text render={<span />} size="xs" variant="muted">
                        {`${template.triggerLabel} · ${template.worksWith.join(', ')}`}
                    </Text>
                </span>
            </ItemContent>
        </Item>
    )
}
