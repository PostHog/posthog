import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useCallback } from 'react'

import { ChatSheet } from '@/features/chat/ChatSheet'

export default function ChatRoute(): ReactElement {
    const router = useRouter()
    const { reportId, taskId, runId } = useLocalSearchParams<{
        reportId?: string
        taskId?: string
        runId?: string
    }>()
    const close = useCallback(() => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace('/inbox')
        }
    }, [router])
    return <ChatSheet initialReportId={reportId} initialTaskId={taskId} initialRunId={runId} onClosed={close} />
}
