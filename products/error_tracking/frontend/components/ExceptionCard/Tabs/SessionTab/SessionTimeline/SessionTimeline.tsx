import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { sessionTabLogic } from '../sessionTabLogic'
import { useActions, useValues } from 'kea'
import { IconVerticalAlignCenter } from 'lib/lemon-ui/icons'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { forwardRef, useCallback, useEffect, useMemo, useRef } from 'react'
import { cva } from 'cva'
import { dayjs } from 'lib/dayjs'
import { Link, Spinner } from '@posthog/lemon-ui'
import { exceptionCardLogic } from '../../../exceptionCardLogic'
import { useScrollObserver } from '../../../../../hooks/use-scroll-observer'
import { useAsyncCallback } from 'products/error_tracking/frontend/hooks/use-async-callback'
import { ItemCollector, ItemRenderer, RendererProps, TimelineItem } from './timeline'
import { cn } from 'lib/utils/css-classes'

const LOADING_DEBOUNCE_OPTIONS = { leading: true, delay: 500 }

export function SessionTimeline({ ...props }: TabsPrimitiveContentProps): JSX.Element {
    const { items, timestamp, sessionId, currentCategories } = useValues(sessionTabLogic)
    const { setItems, toggleCategory } = useActions(sessionTabLogic)
    const { uuid } = useValues(errorPropertiesLogic)
    const { currentSessionTab } = useValues(exceptionCardLogic)

    const collector = useMemo(() => {
        // Add jitter to catch event at exact timestamp
        return new ItemCollector(sessionId, dayjs(timestamp).add(1, 'millisecond'))
    }, [sessionId, timestamp])
    const containerRef = useRef<HTMLDivElement | null>(null)

    const scrollToItem = useCallback((uuid: string) => {
        const item = containerRef.current?.querySelector(`[data-item-id="${uuid}"]`)
        if (item) {
            item.scrollIntoView({ behavior: 'instant', block: 'center' })
        }
    }, [])

    const [loadBefore, beforeLoading] = useAsyncCallback(
        () =>
            collector.loadBefore(currentCategories, 25).then(() => {
                const items = collector.collectItems()
                const containerEl = containerRef.current
                const scrollTop = containerEl?.scrollTop || 0
                const scrollHeight = containerEl?.scrollHeight || 0
                setItems(items)
                // Restore scroll position
                requestAnimationFrame(() => {
                    const newScrollHeight = containerEl?.scrollHeight || 0
                    if (containerEl) {
                        containerEl.scrollTop = scrollTop + (newScrollHeight - scrollHeight)
                    }
                })
            }),
        [collector, currentCategories],
        LOADING_DEBOUNCE_OPTIONS
    )

    const [loadAfter, afterLoading] = useAsyncCallback(
        () =>
            collector.loadAfter(currentCategories, 25).then(() => {
                setItems(collector.collectItems())
            }),
        [collector, currentCategories],
        LOADING_DEBOUNCE_OPTIONS
    )

    useEffect(() => {
        collector.clear()
        Promise.all([loadBefore(), loadAfter()]).then(() => {
            const items = collector.collectItems()
            setItems(items)
            scrollToItem(uuid)
        })
    }, [collector, loadBefore, loadAfter, setItems, scrollToItem, uuid])

    const scrollRefCb = useScrollObserver({
        onScrollTop: () => {
            if (collector.hasBefore(currentCategories)) {
                return loadBefore()
            }
        },
        onScrollBottom: () => {
            if (collector.hasAfter(currentCategories)) {
                return loadAfter()
            }
        },
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
                        {collector.getCategories().map((cat) => (
                            <SessionGroupToggle
                                active={currentCategories.includes(cat)}
                                key={cat}
                                onClick={() => toggleCategory(cat)}
                            >
                                {collector.getRenderer(cat)?.categoryIcon}
                            </SessionGroupToggle>
                        ))}
                    </div>
                    {items.find((item) => item.id === uuid) && (
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
                    {beforeLoading && (
                        <div className={cn(itemContainer({ selected: false }), 'justify-start')}>
                            <Spinner />
                            <span className="text-secondary">loading...</span>
                        </div>
                    )}
                    {items.map((item) => {
                        const renderer = collector.getRenderer(item.category)
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
                    {afterLoading && !beforeLoading && (
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

const itemContainer = cva({
    base: 'flex justify-between gap-2 items-center px-2 w-full h-[2rem]',
    variants: {
        selected: {
            true: 'bg-[var(--gray-1)] border-1 border-accent',
            false: 'border-b border-[var(--gray-2)]',
        },
    },
})

type SessionTimelineItemContainerProps = RendererProps<TimelineItem> & {
    renderer: ItemRenderer<TimelineItem>
    selected: boolean
}

const SessionTimelineItemContainer = forwardRef<HTMLDivElement, SessionTimelineItemContainerProps>(
    function SessionTimelineItemContainer(
        { renderer, item, selected }: SessionTimelineItemContainerProps,
        ref
    ): JSX.Element {
        const { setRecordingTimestamp } = useActions(sessionTabLogic)
        const { setCurrentSessionTab } = useActions(exceptionCardLogic)
        return (
            <div ref={ref} className={itemContainer({ selected })} data-item-id={item.id}>
                <span className="text-xs text-tertiary w-[20px] shrink-0 text-center">
                    <renderer.sourceIcon item={item} />
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
                <div className="shrink-0 w-[20px] text-center">{renderer.categoryIcon}</div>
                <div className="flex-grow">
                    <renderer.render item={item} />
                </div>
            </div>
        )
    }
)

const sessionGroupToggle = cva({
    base: 'shrink-0',
    variants: {
        active: {
            true: 'text-accent',
        },
    },
})

export function SessionGroupToggle({ active, ...props }: ButtonPrimitiveProps): JSX.Element {
    return <ButtonPrimitive iconOnly className={sessionGroupToggle({ active })} {...props} />
}
