import type { ReactElement } from 'react'

import { BrowseListScreen } from '@/features/views/browse/BrowseListScreen'

export default function BrowseInsightsRoute(): ReactElement {
    return <BrowseListScreen kind="insights" />
}
