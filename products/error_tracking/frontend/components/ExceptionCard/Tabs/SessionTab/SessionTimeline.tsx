import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { sessionTabLogic } from './sessionTabLogic'
import { useActions, useValues } from 'kea'
import { IconVerticalAlignCenter } from 'lib/lemon-ui/icons'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { forwardRef, useCallback, useEffect, useMemo, useState, useRef } from 'react'
import {
    PreviewRenderProps,
    SessionTimelineItem,
    SessionTimelineRenderer,
    RendererGroup,
    SessionTimelineEvent,
} from './SessionTimelineItem/base'
import { cva } from 'cva'
import { dayjs } from 'lib/dayjs'
import { IconWarning, IconToggle, IconGraph, IconMessage, IconPieChart, IconLogomark } from '@posthog/icons'
import { match } from 'ts-pattern'
import { Link, Spinner } from '@posthog/lemon-ui'
import { exceptionCardLogic } from '../../exceptionCardLogic'
import { EventsItemLoader } from './SessionTimelineItem/loader'
import { useScrollObserver } from '../../../../hooks/use-scroll-observer'
import { cn } from 'lib/utils/css-classes'
import { useAsyncCallback } from 'products/error_tracking/frontend/hooks/use-async-callback'

const groupIconMapping: Record<RendererGroup, React.ReactNode> = {
    [RendererGroup.ERROR_TRACKING]: <IconWarning />,
    [RendererGroup.PRODUCT_ANALYTICS]: <IconGraph />,
    [RendererGroup.WEB_ANALYTICS]: <IconPieChart />,
    [RendererGroup.FEATURE_FLAGS]: <IconToggle />,
    [RendererGroup.SURVEYS]: <IconMessage />,
    [RendererGroup.INTERNALS]: <IconLogomark />,
}

export function SessionTimeline({ ...props }: TabsPrimitiveContentProps): JSX.Element {
    const { filteredItems, timestamp, sessionId, usedGroups } = useValues(sessionTabLogic)
    const { setEvents } = useActions(sessionTabLogic)
    const { uuid } = useValues(errorPropertiesLogic)
    const { currentSessionTab } = useValues(exceptionCardLogic)
    const [loading, setLoading] = useState(false)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const eventsLoader = useMemo(() => new EventsItemLoader(timestamp, sessionId), [timestamp, sessionId])

    const scrollToItem = useCallback((uuid: string) => {
        const item = document.querySelector(`[data-item-id="${uuid}"]`)
        if (item) {
            item.scrollIntoView({ behavior: 'instant', block: 'center' })
        }
    }, [])

    useEffect(() => {
        setLoading(true)
        eventsLoader
            .load()
            .then(setEvents)
            .finally(() => {
                setLoading(false)
                scrollToItem(uuid)
            })
    }, [eventsLoader, setLoading, scrollToItem, uuid, setEvents])

    const loadBefore = useAsyncCallback(eventsLoader.loadBefore.bind(eventsLoader), [eventsLoader], {
        delay: 500,
        onDone: (events: SessionTimelineEvent[]) => {
            const containerEl = containerRef.current
            const scrollTop = containerEl?.scrollTop || 0
            const scrollHeight = containerEl?.scrollHeight || 0
            setEvents(events)
            // Restore scroll position to avoid staying at the top of the container
            requestAnimationFrame(() => {
                const newScrollHeight = containerEl?.scrollHeight || 0
                if (containerEl) {
                    containerEl.scrollTop = scrollTop + (newScrollHeight - scrollHeight)
                }
            })
        },
    })

    const loadAfter = useAsyncCallback(eventsLoader.loadAfter.bind(eventsLoader), [eventsLoader], {
        delay: 500,
        onDone: setEvents,
    })

    const scrollRefCb = useScrollObserver({
        onScrollTop: loadBefore,
        onScrollBottom: loadAfter,
    })

    useEffect(() => {
        requestAnimationFrame(() => {
            // Scroll to item on tab change
            scrollToItem(uuid)
        })
    }, [uuid, scrollToItem, currentSessionTab])

    return (
        <TabsPrimitiveContent {...props}>
            <div className="flex">
                <div className="flex flex-col justify-between items-center p-1 border-r border-gray-3">
                    <div className="flex flex-col items-center gap-2">
                        {match(loading)
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
                    {filteredItems.find(([item]) => item.id === uuid) && (
                        <ButtonPrimitive iconOnly onClick={() => scrollToItem(uuid)}>
                            <IconVerticalAlignCenter />
                        </ButtonPrimitive>
                    )}
                </div>
                <div
                    ref={(el) => {
                        scrollRefCb(el)
                        containerRef.current = el
                    }}
                    className="h-[500px] w-full overflow-y-auto relative"
                    style={{ scrollbarGutter: 'stable' }}
                >
                    {loadBefore.isPending() && (
                        <div className={cn(itemContainer({ selected: false }), 'justify-start')}>
                            <Spinner />
                            <span className="text-secondary">loading...</span>
                        </div>
                    )}
                    {filteredItems.map(([item, renderer]) => {
                        return (
                            <SessionTimelineItemContainer
                                renderer={renderer}
                                key={item.id}
                                item={item}
                                selected={item.id === uuid}
                            />
                        )
                    })}
                    {loadAfter.isPending() && (
                        <div className={cn(itemContainer({ selected: false }), 'justify-start')}>
                            <Spinner />
                            <span className="text-secondary">loading...</span>
                        </div>
                    )}
                </div>
            </div>
        </TabsPrimitiveContent>
    )
}

const itemContainer = cva('flex justify-between gap-2 items-center px-2 w-full h-[2rem]', {
    variants: {
        selected: {
            true: 'bg-[var(--gray-1)] border-1 border-accent',
            false: 'border-b border-[var(--gray-3)]',
        },
    },
})

type SessionTimelineItemContainerProps = PreviewRenderProps<SessionTimelineItem> & {
    renderer: SessionTimelineRenderer<SessionTimelineItem>
}
const SessionTimelineItemContainer = forwardRef<HTMLDivElement, SessionTimelineItemContainerProps>(
    function SessionTimelineItemContainer(
        { renderer, item, selected, ...props }: SessionTimelineItemContainerProps,
        ref
    ): JSX.Element {
        const { setRecordingTimestamp } = useActions(sessionTabLogic)
        const { setCurrentSessionTab } = useActions(exceptionCardLogic)
        return (
            <div ref={ref} className={itemContainer({ selected })} data-item-id={item.id}>
                <span className="text-xs text-tertiary w-[20px] shrink-0 text-center">
                    <renderer.runtimeIcon item={item} selected={selected} {...props} />
                </span>
                <span className="text-xs text-tertiary w-[50px] shrink-0 text-center">
                    <Link
                        className="text-tertiary hover:text-accent"
                        onClick={() => {
                            setRecordingTimestamp(item.timestamp, 1000)
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
        )
    }
)

const sessionGroupToggle = cva('shrink-0', {
    variants: {
        active: {
            true: 'text-accent',
        },
    },
})

export function SessionGroupToggle({
    group,
    ...props
}: ButtonPrimitiveProps & {
    group: RendererGroup
}): JSX.Element {
    const { isGroupActive } = useValues(sessionTabLogic)
    const { toggleGroup } = useActions(sessionTabLogic)
    return (
        <ButtonPrimitive
            iconOnly
            className={sessionGroupToggle({ active: isGroupActive(group) })}
            onClick={() => toggleGroup(group)}
            {...props}
        />
    )
}
