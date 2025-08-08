import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'
import { ItemCategory, ItemLoaderFactory, ItemRenderer, TimelineItem } from '..'
import { BasePreview, EventLoader } from './base'
import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { Link } from '@posthog/lemon-ui'
import { IconEye } from '@posthog/icons'
import { dayjs, Dayjs } from 'lib/dayjs'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'

export interface PageItem extends TimelineItem {
    payload: {
        runtime: ErrorTrackingRuntime
        url: string
    }
}

export const pageRenderer: ItemRenderer<PageItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconEye />,
    render: ({ item }): JSX.Element => {
        return (
            <BasePreview
                name="Pageview"
                description={
                    <Link className="text-secondary hover:text-accent" subtle to={item.payload.url} target="_blank">
                        {getUrlPathname(item.payload.url)}
                    </Link>
                }
            />
        )
    },
}

export class PageItemLoader extends EventLoader<PageItem> {
    select(): string[] {
        return ['uuid', 'timestamp', 'properties.$current_url', 'properties.$lib']
    }

    where(): string[] {
        return ["equals(event, '$pageview')"]
    }

    buildItem(evt: any): PageItem {
        return {
            id: evt[0],
            category: ItemCategory.PRODUCT_ANALYTICS,
            timestamp: dayjs.utc(evt[1]),
            payload: {
                runtime: getRuntimeFromLib(evt[3]),
                url: evt[2],
            },
        } as PageItem
    }
}

export const pageLoader: ItemLoaderFactory<PageItem> = (sessionId: string, timestamp: Dayjs) => {
    const excLoader = new PageItemLoader(sessionId, timestamp)
    return {
        hasPrevious: excLoader.hasPrevious.bind(excLoader),
        previous: excLoader.previous.bind(excLoader),
        hasNext: excLoader.hasNext.bind(excLoader),
        next: excLoader.next.bind(excLoader),
    }
}

function getUrlPathname(url: string): string {
    try {
        const parsedUrl = new URL(url)
        return parsedUrl.pathname
    } catch {
        return url
    }
}
