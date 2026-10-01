import { IconCloud, IconLaptop, IconListCheck } from '@posthog/icons'

import { TaskRunEnvironment } from '../types/taskTypes'
import { getOriginProductMeta } from './taskSourceMeta'

export function TaskSourceIcon({
    originProduct,
    environment,
}: {
    originProduct?: string
    environment?: TaskRunEnvironment
}): JSX.Element {
    const originMeta = getOriginProductMeta(originProduct)
    if (originMeta) {
        return originMeta.icon
    }
    if (environment === TaskRunEnvironment.CLOUD) {
        return <IconCloud />
    }
    if (environment === TaskRunEnvironment.LOCAL) {
        return <IconLaptop />
    }
    return <IconListCheck />
}
