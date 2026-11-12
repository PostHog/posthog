import {
    IconBell,
    IconBolt,
    IconBox,
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconGlobe,
    IconGraph,
    IconList,
    IconNotebook,
    IconNotification,
    IconPeople,
    IconPerson,
    IconRocket,
    IconSparkles,
    IconStar,
    IconTarget,
    IconTrending,
    IconWarning,
} from '@posthog/icons'

import { Logomark } from 'lib/brand'

import type { FragmentIconApi } from './generated/api.schemas'

export const SIDEBAR_ICONS: Record<FragmentIconApi, JSX.Element> = {
    list: <IconList />,
    person: <IconPerson />,
    people: <IconPeople />,
    box: <IconBox />,
    bell: <IconBell />,
    notification: <IconNotification />,
    posthog: <Logomark className="h-auto w-3.5" />,
    chart: <IconGraph />,
    dashboard: <IconDashboard />,
    notebook: <IconNotebook />,
    sql: <IconDatabase />,
    star: <IconStar />,
    rocket: <IconRocket />,
    target: <IconTarget />,
    trending: <IconTrending />,
    globe: <IconGlobe />,
    sparkle: <IconSparkles />,
    bolt: <IconBolt />,
    flag: <IconFlag />,
    warning: <IconWarning />,
}
