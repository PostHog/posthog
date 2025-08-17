import { Dayjs } from 'lib/dayjs'

import { customItemLoader, customItemRenderer } from './items/custom'
import { exceptionLoader, exceptionRenderer } from './items/exceptions'
import { pageLoader, pageRenderer } from './items/page'

export enum ItemCategory {
    ERROR_TRACKING = 'error-tracking',
    CUSTOM_EVENTS = 'custom-events',
    PAGE_VIEWS = 'page-views',
}

export interface TimelineItem {
    id: string
    category: ItemCategory
    timestamp: Dayjs
    payload: any
}

export interface RendererProps<T extends TimelineItem> {
    item: T
}

export type ItemRenderer<T extends TimelineItem> = {
    sourceIcon: React.FC<RendererProps<T>>
    categoryIcon: React.ReactNode
    render: React.FC<RendererProps<T>>
}

export type ItemLoader<T extends TimelineItem> = {
    hasPrevious(index: Dayjs): boolean
    previous(index: Dayjs, limit?: number): Promise<T | null>

    hasNext(index: Dayjs): boolean
    next(index: Dayjs, limit?: number): Promise<T | null>
}

export type ItemLoaderFactory<T extends TimelineItem> = (sessionId: string, timestamp: Dayjs) => ItemLoader<T>

export class ItemCache<T extends TimelineItem> {
    orderedIds: string[]
    queue: Record<string, T>

    constructor() {
        this.queue = {}
        this.orderedIds = []
    }

    private sort(): void {
        this.orderedIds = Object.keys(this.queue).sort((a, b) => this.queue[a].timestamp.diff(this.queue[b].timestamp))
    }

    clear(): void {
        this.queue = {}
        this.orderedIds = []
    }

    getAll(): T[] {
        return this.orderedIds.map((id) => this.queue[id])
    }

    add(items: T[]): void {
        for (const item of items) {
            this.queue[item.id] = item
        }
        this.sort()
    }

    next(from: Dayjs): T | undefined {
        for (const id of this.orderedIds) {
            const item = this.queue[id]
            if (item.timestamp.isAfter(from)) {
                return item
            }
        }
    }

    previous(to: Dayjs): T | undefined {
        for (let i = this.orderedIds.length - 1; i >= 0; i--) {
            const id = this.orderedIds[i]
            const item = this.queue[id]
            if (item.timestamp.isBefore(to)) {
                return item
            }
        }
    }
}

export class ItemCollector {
    sessionId: string
    timestamp: Dayjs
    beforeCursor: Dayjs
    afterCursor: Dayjs
    itemCache: ItemCache<TimelineItem>
    loaders: Map<ItemCategory, ItemLoader<TimelineItem>> = new Map()
    renderers: Map<ItemCategory, ItemRenderer<TimelineItem>> = new Map()

    constructor(sessionId: string, timestamp: Dayjs) {
        this.sessionId = sessionId
        this.timestamp = timestamp
        this.beforeCursor = this.timestamp
        this.afterCursor = this.timestamp
        this.itemCache = new ItemCache<TimelineItem>()
        this.addCategory(ItemCategory.ERROR_TRACKING, exceptionRenderer, exceptionLoader(sessionId, this.timestamp))
        this.addCategory(ItemCategory.PAGE_VIEWS, pageRenderer, pageLoader(sessionId, this.timestamp))
        this.addCategory(ItemCategory.CUSTOM_EVENTS, customItemRenderer, customItemLoader(sessionId, this.timestamp))
    }

    addCategory(category: ItemCategory, renderer: ItemRenderer<TimelineItem>, loader: ItemLoader<TimelineItem>): void {
        this.loaders.set(category, loader)
        this.renderers.set(category, renderer)
    }

    getAllCategories(): ItemCategory[] {
        return Array.from(this.loaders.keys())
    }

    findMinTimestamp(array: TimelineItem[]): TimelineItem {
        return array.slice().sort((a, b) => a.timestamp.diff(b.timestamp))[0]
    }

    findMaxTimestamp(array: TimelineItem[]): TimelineItem {
        return array.slice().sort((a, b) => b.timestamp.diff(a.timestamp))[0]
    }

    clear(): void {
        this.beforeCursor = this.timestamp
        this.afterCursor = this.timestamp
        this.itemCache = new ItemCache<TimelineItem>()
    }

    getRenderer(category: ItemCategory): ItemRenderer<TimelineItem> | undefined {
        return this.renderers.get(category)
    }

    getLoader(category: ItemCategory): ItemLoader<TimelineItem> | undefined {
        return this.loaders.get(category)
    }

    getCategories(): ItemCategory[] {
        return Array.from(this.loaders.keys())
    }

    collectItems(): TimelineItem[] {
        return this.itemCache.getAll()
    }

    hasBefore(categories: ItemCategory[]): boolean {
        return categories
            .map((cat) => this.getLoader(cat))
            .some((loader) => !!loader && loader.hasPrevious(this.beforeCursor))
    }

    hasAfter(categories: ItemCategory[]): boolean {
        return categories
            .map((cat) => this.getLoader(cat))
            .some((loader) => !!loader && loader.hasNext(this.afterCursor))
    }

    async loadBefore(categories: ItemCategory[], count: number): Promise<void> {
        const items = []
        let currentLoaders = categories
            .map((cat) => this.getLoader(cat))
            .filter((loader) => !!loader) as ItemLoader<TimelineItem>[]

        while (items.length < count) {
            const previousItems = await Promise.all(
                currentLoaders.map((loader) => loader.previous(this.beforeCursor, count))
            )
            const maxItem = this.findMaxTimestamp(previousItems.filter((item) => item !== null) as TimelineItem[])
            if (maxItem) {
                items.push(maxItem)
                this.beforeCursor = maxItem.timestamp
            } else {
                break
            }
        }
        this.itemCache.add(items)
    }

    async loadAfter(categories: ItemCategory[], count: number): Promise<void> {
        const items = []
        let currentLoaders = categories
            .map((cat) => this.getLoader(cat))
            .filter((loader) => !!loader) as ItemLoader<TimelineItem>[]
        while (items.length < count) {
            const nextItems = await Promise.all(currentLoaders.map((loader) => loader.next(this.afterCursor, count)))
            const minItem = this.findMinTimestamp(nextItems.filter((item) => item !== null) as TimelineItem[])
            if (minItem) {
                items.push(minItem)
                this.afterCursor = minItem.timestamp
            } else {
                break
            }
        }
        this.itemCache.add(items)
    }
}
