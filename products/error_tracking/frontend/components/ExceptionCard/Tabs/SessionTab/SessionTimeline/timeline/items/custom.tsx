import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'
import { ItemCategory, ItemLoaderFactory, ItemRenderer, TimelineItem } from '..'
import { BasePreview, EventLoader } from './base'
import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { IconGraph } from '@posthog/icons'
import { dayjs, Dayjs } from 'lib/dayjs'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'

export interface CustomItem extends TimelineItem {
    payload: {
        name: string
        runtime: ErrorTrackingRuntime
    }
}

export const customItemRenderer: ItemRenderer<CustomItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconGraph />,
    render: ({ item }): JSX.Element => {
        return <BasePreview name={item.payload.name} />
    },
}

export class CustomItemLoader extends EventLoader<CustomItem> {
    select(): string[] {
        return ['uuid', 'event', 'timestamp', 'properties.$lib']
    }

    where(): string[] {
        return ["notEquals(left(event, 1), '$')"]
    }

    buildItem(evt: [string, string, string, string]): CustomItem {
        return {
            id: evt[0],
            category: ItemCategory.CUSTOM_EVENTS,
            timestamp: dayjs.utc(evt[2]),
            payload: {
                runtime: getRuntimeFromLib(evt[3]),
                name: evt[1],
            },
        } as CustomItem
    }
}

export const customItemLoader: ItemLoaderFactory<CustomItem> = (sessionId: string, timestamp: Dayjs) => {
    const customEvtLoader = new CustomItemLoader(sessionId, timestamp)
    return {
        hasPrevious: customEvtLoader.hasPrevious.bind(customEvtLoader),
        previous: customEvtLoader.previous.bind(customEvtLoader),
        hasNext: customEvtLoader.hasNext.bind(customEvtLoader),
        next: customEvtLoader.next.bind(customEvtLoader),
    }
}
