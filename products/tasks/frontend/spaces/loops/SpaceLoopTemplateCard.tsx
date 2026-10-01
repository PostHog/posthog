import { IconBolt, IconClock, IconPlug } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, Text, cn } from '@posthog/quill'

import { SpaceLoopTemplate, SpaceLoopTemplateTone } from './spaceLoopTemplates'

const TONE_CLASSES: Record<SpaceLoopTemplateTone, string> = {
    info: 'bg-info text-info-foreground',
    destructive: 'bg-destructive text-destructive-foreground',
    completed: 'bg-completed text-completed-foreground',
    success: 'bg-success text-success-foreground',
    warning: 'bg-warning text-warning-foreground',
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
            variant="pressable"
            render={<button type="button" onClick={onSelect} />}
            className="h-full items-start text-left"
            data-attr="today-space-loop-template"
        >
            <ItemMedia variant="icon" className={cn('rounded-md', TONE_CLASSES[template.tone])}>
                <Icon />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle>{template.name}</ItemTitle>
                <ItemDescription className="line-clamp-none">{template.description}</ItemDescription>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
                    <span className="flex items-center gap-1">
                        <TriggerIcon className="size-3 shrink-0" />
                        <Text render={<span />} size="xs" variant="muted">
                            {template.triggerLabel}
                        </Text>
                    </span>
                    <span className="flex items-center gap-1">
                        <IconPlug className="size-3 shrink-0" />
                        <Text render={<span />} size="xs" variant="muted">
                            {`Works with ${template.worksWith.join(' · ')}`}
                        </Text>
                    </span>
                </div>
            </ItemContent>
        </Item>
    )
}
