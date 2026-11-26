import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useCallback } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDataMode } from '@/demo/demoMode'
import { ChatEntryScreen } from '@/features/chat/ChatEntryScreen'
import { chatSheetSource } from '@/features/chat/chatSheetEvents'
import { objectContextFromParams } from '@/features/chat/objectContext'
import { useChatAutoFocus } from '@/features/chat/useChatAutoFocus'
import { currentDefaultPageHref } from '@/features/settings/defaultPageStore'

export default function ChatRoute(): ReactElement {
    const router = useRouter()
    const host = useAuthStore((state) => state.host)
    const userUuid = useAuthStore((state) => state.user?.uuid)
    const projectId = useAuthStore((state) => state.projectId)
    const dataMode = useDataMode()
    const autoFocus = useChatAutoFocus()
    const { reportId, taskId, runId, conversationId, entry, origin, objectType, objectId, objectLabel } =
        useLocalSearchParams<{
            reportId?: string
            taskId?: string
            runId?: string
            conversationId?: string
            entry?: string
            origin?: string
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
        <ChatEntryScreen
            key={JSON.stringify([
                host,
                userUuid,
                projectId,
                dataMode,
                taskId,
                runId,
                reportId,
                objectId,
                conversationId,
            ])}
            conversationId={conversationId}
            initialReportId={reportId}
            initialTaskId={taskId}
            initialRunId={runId}
            initialObject={objectContextFromParams({ objectType, objectId, objectLabel })}
            source={chatSheetSource({ entry, origin, reportId, taskId, objectType })}
            autoFocus={autoFocus}
            onBack={close}
        />
    )
}
