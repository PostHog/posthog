import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useCallback } from 'react'

import { useDataMode } from '@/demo/demoMode'
import { ChatSheet } from '@/features/chat/ChatSheet'
import { chatSheetSource } from '@/features/chat/chatSheetEvents'
import { currentDefaultPageHref } from '@/features/settings/defaultPageStore'

export default function ChatRoute(): ReactElement {
    const router = useRouter()
    const dataMode = useDataMode()
    const { reportId, taskId, runId, entry, origin } = useLocalSearchParams<{
        reportId?: string
        taskId?: string
        runId?: string
        entry?: string
        origin?: string
    }>()
    const close = useCallback(() => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace(currentDefaultPageHref())
        }
    }, [router])
    return (
        <ChatSheet
            key={JSON.stringify([dataMode, taskId, runId, reportId])}
            initialReportId={reportId}
            initialTaskId={taskId}
            initialRunId={runId}
            source={chatSheetSource({ entry, origin, reportId, taskId })}
            onClosed={close}
        />
    )
}
