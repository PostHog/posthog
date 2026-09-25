import { IconCloud, IconLaptop, IconListCheck } from '@posthog/icons'

import { TaskRunEnvironment } from '../types/taskTypes'

export function TaskEnvironmentIcon({ environment }: { environment?: TaskRunEnvironment }): JSX.Element {
    if (environment === TaskRunEnvironment.CLOUD) {
        return <IconCloud />
    }
    if (environment === TaskRunEnvironment.LOCAL) {
        return <IconLaptop />
    }
    return <IconListCheck />
}
