import type { ReactElement } from 'react'

import { ReplayListScreen } from '@/features/replay/ReplayListScreen'

export default function ReplayListRoute(): ReactElement {
    return <ReplayListScreen chrome="stack" />
}
