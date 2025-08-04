import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { sessionTabLogic } from './sessionTabLogic'
import { useActions, useValues } from 'kea'
import { IconVerticalAlignCenter } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { useLayoutEffect } from 'react'
import {
    PreviewRenderProps,
    SessionTimelineItem,
    SessionTimelineRenderer,
    RendererGroup,
} from './SessionTimelineItem/base'
import { cva } from 'cva'
import { dayjs } from 'lib/dayjs'
import { IconWarning, IconToggle, IconGraph, IconMessage, IconPieChart, IconLogomark } from '@posthog/icons'
import { match } from 'ts-pattern'
import { Link, Spinner } from '@posthog/lemon-ui'
import { exceptionCardLogic } from '../../exceptionCardLogic'

const groupIconMapping: Record<RendererGroup, React.ReactNode> = {
    [RendererGroup.ERROR_TRACKING]: <IconWarning />,
    [RendererGroup.PRODUCT_ANALYTICS]: <IconGraph />,
    [RendererGroup.WEB_ANALYTICS]: <IconPieChart />,
    [RendererGroup.FEATURE_FLAGS]: <IconToggle />,
    [RendererGroup.SURVEYS]: <IconMessage />,
    [RendererGroup.INTERNALS]: <IconLogomark />,
}

export function SessionTimeline({ ...props }: TabsPrimitiveContentProps): JSX.Element {
    const { items, itemsLoading, eventListEl, eventsLoading, getRenderer, usedGroups, canScrollToItem } =
        useValues(sessionTabLogic)
    const { setEventListEl, scrollToItem } = useActions(sessionTabLogic)
    const { uuid } = useValues(errorPropertiesLogic)

    useLayoutEffect(() => {
        if (uuid && !eventsLoading) {
            scrollToItem(uuid)
        }
    }, [uuid, eventsLoading, eventListEl, scrollToItem])

    return (
        <TabsPrimitiveContent {...props}>
            <div className="flex">
                <div className="flex flex-col justify-between items-center p-1 border-r border-gray-3">
                    <div className="flex flex-col items-center gap-2">
                        {match(itemsLoading)
                            .with(true, () => (
                                <ButtonPrimitive iconOnly disabled={true}>
                                    <Spinner />
                                </ButtonPrimitive>
                            ))
                            .with(false, () =>
                                usedGroups.map((group) => (
                                    <SessionGroupToggle group={group} key={group}>
                                        {groupIconMapping[group] as React.ReactNode}
                                    </SessionGroupToggle>
                                ))
                            )
                            .exhaustive()}
                    </div>
                    {canScrollToItem(uuid) && (
                        <ButtonPrimitive iconOnly onClick={() => scrollToItem(uuid)}>
                            <IconVerticalAlignCenter />
                        </ButtonPrimitive>
                    )}
                </div>
                <div
                    ref={(el) => setEventListEl(el)}
                    className="flex flex-col h-[500px] w-full overflow-y-auto relative"
                    style={{ scrollbarGutter: 'stable' }}
                >
                    {match(itemsLoading)
                        .with(true, () => <div className="p-2">Loading events...</div>)
                        .with(false, () =>
                            items.map((item) => {
                                const renderer = getRenderer(item)
                                if (!renderer) {
                                    return null
                                }
                                return (
                                    <SessionTimelineItemContainer
                                        renderer={renderer}
                                        key={item.id}
                                        item={item}
                                        selected={item.id === uuid}
                                    />
                                )
                            })
                        )
                        .exhaustive()}
                </div>
            </div>
        </TabsPrimitiveContent>
    )
}

const itemContainer = cva('flex flex-col', {
    variants: {
        selected: {
            true: 'bg-[var(--gray-1)] border-1 border-accent',
            false: 'border-b border-[var(--gray-3)]',
        },
    },
})

const itemPreview = cva('flex justify-between gap-2 items-center px-2 py-1 w-full', {
    variants: {},
})

export function SessionTimelineItemContainer<T extends SessionTimelineItem>({
    renderer,
    item,
    selected,
    ...props
}: PreviewRenderProps<T> & { renderer: SessionTimelineRenderer<T> }): JSX.Element {
    const { goToTimestamp } = useActions(sessionTabLogic)
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)
    return (
        <div className={itemContainer({ selected })} data-item-id={item.id}>
            <div className={itemPreview()}>
                <span className="text-xs text-tertiary w-[20px] shrink-0 text-center">
                    <renderer.runtimeIcon item={item} selected={selected} {...props} />
                </span>
                <span className="text-xs text-tertiary w-[50px] shrink-0 text-center">
                    <Link
                        className="text-tertiary hover:text-accent"
                        onClick={() => {
                            goToTimestamp(item.timestamp, 1000)
                            setCurrentSessionTab('recording')
                        }}
                    >
                        {dayjs(item.timestamp).format('HH:mm:ss')}
                    </Link>
                </span>
                <div className="shrink-0 w-[20px] text-center">{groupIconMapping[renderer.group]}</div>
                <div className="flex-grow">
                    <renderer.renderPreview item={item} selected={selected} {...props} />
                </div>
            </div>
        </div>
    )
}

const sessionGroupToggle = cva('flex justify-between gap-2 items-center px-2 py-1 w-full shrink-0', {
    variants: {
        active: {
            true: 'text-accent',
        },
    },
})

export function SessionGroupToggle({
    group,
    children,
}: {
    group: RendererGroup
    children: React.ReactNode
}): JSX.Element {
    const { isGroupActive } = useValues(sessionTabLogic)
    const { toggleGroup } = useActions(sessionTabLogic)
    return (
        <ButtonPrimitive
            iconOnly
            className={sessionGroupToggle({ active: isGroupActive(group) })}
            onClick={() => toggleGroup(group)}
        >
            {children}
        </ButtonPrimitive>
    )
}
