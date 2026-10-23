import { useLocalSearchParams } from 'expo-router'
import type { ReactElement } from 'react'

import { issueOpenSourceParam } from '@/features/errors/analytics'
import { IssueScreen } from '@/features/errors/IssueScreen'
import { windowParam } from '@/features/errors/issueModel'

export default function IssueRoute(): ReactElement {
    const { id, from, window } = useLocalSearchParams<{ id: string; from?: string; window?: string }>()
    return <IssueScreen issueId={id ?? ''} from={issueOpenSourceParam(from)} window={windowParam(window)} />
}
