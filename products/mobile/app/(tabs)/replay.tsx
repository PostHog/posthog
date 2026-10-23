import type { ReactElement } from 'react'

import { ReplayListScreen } from '@/features/replay/ReplayListScreen'

export default function ReplayTabRoute(): ReactElement {
    return <ReplayListScreen chrome="tab" />
}
