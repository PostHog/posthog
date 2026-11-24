import { useActions, useValues } from 'kea'

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

import { SEASONAL_ITEM_ICONS, SeasonalChecklistItem } from './seasonalChecklist'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'

export function TodaySeasonalChecklistRow({ item }: { item: SeasonalChecklistItem }): JSX.Element {
    const { doneKeys, nextItemKey } = useValues(todaySeasonalChecklistLogic)
    const { setItemDone, itemActionClicked } = useActions(todaySeasonalChecklistLogic)
    const done = doneKeys.has(item.key)
    const Icon = item.icon ? SEASONAL_ITEM_ICONS[item.icon] : null
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
