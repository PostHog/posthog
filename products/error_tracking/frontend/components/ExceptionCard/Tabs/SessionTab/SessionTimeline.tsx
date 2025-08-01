import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { sessionTabLogic } from './sessionTabLogic'
import { useActions, useValues } from 'kea'
import { IconVerticalAlignCenter } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { useLayoutEffect, useState } from 'react'
import {
    PreviewRenderProps,
    SessionTimelineItem,
    SessionTimelineRenderer,
    RendererGroup,
} from './SessionTimelineItem/base'
import { cva } from 'cva'
import { dayjs } from 'lib/dayjs'
import { IconCollapse, IconExpand, IconWarning, IconToggle, IconGraph, IconMessage, IconPieChart } from '@posthog/icons'

export function SessionTimeline({ ...props }: TabsPrimitiveContentProps): JSX.Element {
    const { items, eventListEl, eventsLoading, getRenderer } = useValues(sessionTabLogic)
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
                        <SessionGroupToggle group="error-tracking">
                            <IconWarning />
                        </SessionGroupToggle>
                        <SessionGroupToggle group="feature-flags">
                            <IconToggle />
                        </SessionGroupToggle>
                        <SessionGroupToggle group="product-analytics">
                            <IconGraph />
                        </SessionGroupToggle>
                        <SessionGroupToggle group="web-analytics">
                            <IconPieChart />
                        </SessionGroupToggle>
                        <SessionGroupToggle group="surveys">
                            <IconMessage />
                        </SessionGroupToggle>
                    </div>
                    <ButtonPrimitive iconOnly onClick={() => scrollToItem(uuid)}>
                        <IconVerticalAlignCenter />
                    </ButtonPrimitive>
                </div>
                <div
                    ref={(el) => setEventListEl(el)}
                    className="flex flex-col h-[500px] w-full overflow-y-auto relative"
                    style={{ scrollbarGutter: 'stable' }}
                >
                    {items.map((item) => {
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
                    })}
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
    const [isOpen, setIsOpen] = useState(false)
    return (
        <div className={itemContainer({ selected })} data-item-id={item.id}>
            <div className={itemPreview()}>
                <span className="text-xs text-tertiary w-[50px] shrink-0">
                    {dayjs(item.timestamp).format('HH:mm:ss')}
                </span>
                <div className="shrink-0 w-[24px] text-center">
                    <renderer.icon />
                </div>
                <div className="flex-grow">
                    <renderer.renderPreview item={item} selected={selected} {...props} />
                </div>
                <ButtonPrimitive iconOnly onClick={() => setIsOpen(!isOpen)}>
                    {isOpen ? <IconCollapse /> : <IconExpand />}
                </ButtonPrimitive>
            </div>
            <div className="bg-[var(--gray-1)]">
                {isOpen && <renderer.renderDetails item={item} selected={selected} {...props} />}
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
