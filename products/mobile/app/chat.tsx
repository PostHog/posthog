import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useCallback } from 'react'

import { useDataMode } from '@/demo/demoMode'
import { ChatScreen } from '@/features/chat/ChatScreen'
import { chatSheetSource } from '@/features/chat/chatSheetEvents'
import { objectContextFromParams } from '@/features/chat/objectContext'
import { currentDefaultPageHref } from '@/features/settings/defaultPageStore'

export default function ChatRoute(): ReactElement {
    const router = useRouter()
    const dataMode = useDataMode()
    const { reportId, taskId, runId, entry, origin, objectType, objectId, objectLabel, from } = useLocalSearchParams<{
        reportId?: string
        taskId?: string
        runId?: string
        entry?: string
        origin?: string
        from?: string
        objectType?: string
        objectId?: string
        objectLabel?: string
    }>()
    const close = useCallback(() => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace(currentDefaultPageHref())
        }
    }, [router])
    return (
        <ChatScreen
            key={JSON.stringify([dataMode, taskId, runId, reportId, objectId])}
            initialReportId={reportId}
            initialTaskId={taskId}
            initialRunId={runId}
            initialObject={objectContextFromParams({ objectType, objectId, objectLabel })}
            source={chatSheetSource({ entry, origin, reportId, taskId, objectType, from })}
            onBack={close}
        />
    )
}
