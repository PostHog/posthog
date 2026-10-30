import type { ReactElement } from 'react'

import { BrowseListScreen } from '@/features/views/browse/BrowseListScreen'

export default function BrowseDashboardsRoute(): ReactElement {
    return <BrowseListScreen kind="dashboards" />
}
