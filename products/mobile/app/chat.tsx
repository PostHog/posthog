import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useCallback } from 'react'

import { ChatSheet } from '@/features/chat/ChatSheet'
import { chatSheetSource } from '@/features/chat/chatSheetEvents'

export default function ChatRoute(): ReactElement {
    const router = useRouter()
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
            router.replace('/inbox')
        }
    }, [router])
    return (
        <ChatSheet
            initialReportId={reportId}
            initialTaskId={taskId}
            initialRunId={runId}
            source={chatSheetSource({ entry, origin, reportId, taskId })}
            onClosed={close}
        />
    )
}
