import { useActions, useValues } from 'kea'

import {
    IconBell,
    IconBug,
    IconCheck,
    IconFlag,
    IconGraph,
    IconLaptop,
    IconMessage,
    IconNotification,
    IconPlug,
    IconPulse,
    IconRocket,
    IconServer,
    IconSparkles,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Checkbox,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SeasonalChecklistItem, SeasonalItemIcon } from './seasonalChecklist'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'

const ICONS: Record<SeasonalItemIcon, typeof IconBell> = {
    bell: IconBell,
    bug: IconBug,
    check: IconCheck,
    flag: IconFlag,
    graph: IconGraph,
    laptop: IconLaptop,
    message: IconMessage,
    notification: IconNotification,
    plug: IconPlug,
    pulse: IconPulse,
    rocket: IconRocket,
    server: IconServer,
    sparkles: IconSparkles,
    toggle: IconToggle,
    warning: IconWarning,
}

export function TodaySeasonalChecklistRow({ item }: { item: SeasonalChecklistItem }): JSX.Element {
    const { doneKeys, nextItemKey } = useValues(todaySeasonalChecklistLogic)
    const { setItemDone, itemActionClicked } = useActions(todaySeasonalChecklistLogic)
    const done = doneKeys.has(item.key)
    const Icon = item.icon ? ICONS[item.icon] : null
    const external = item.url?.startsWith('https://') ?? false

    return (
        <Item data-attr="today-seasonal-checklist-item">
            <ItemMedia>
                <Checkbox
                    checked={done}
                    onCheckedChange={(checked: boolean) => setItemDone(item.key, checked, 'checkbox')}
                    aria-label={`Mark "${item.title}" as done`}
                    data-attr="today-seasonal-checklist-checkbox"
                />
            </ItemMedia>
            {Icon ? (
                <ItemMedia variant="icon">
                    <Icon />
                </ItemMedia>
            ) : null}
            <ItemContent>
                <ItemTitle className={done ? 'text-muted-foreground' : undefined}>{item.title}</ItemTitle>
                <ItemDescription className="line-clamp-none">{item.description}</ItemDescription>
            </ItemContent>
            <ItemActions>
                {done ? (
                    <Badge variant="completed">Done</Badge>
                ) : item.url && item.actionLabel ? (
                    <Button
                        variant={nextItemKey === item.key ? 'primary' : 'outline'}
                        nativeButton={false}
                        render={<LinkPrimitive to={item.url} target={external ? '_blank' : undefined} />}
                        onClick={() => itemActionClicked(item.key)}
                        data-attr="today-seasonal-checklist-action"
                    >
                        {item.actionLabel}
                    </Button>
                ) : null}
            </ItemActions>
        </Item>
    )
}
