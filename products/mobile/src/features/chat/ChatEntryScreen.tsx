import { useQuery } from '@tanstack/react-query'
import { type ComponentProps, type ReactElement, useState } from 'react'
import { View } from 'react-native'

import { getConversation } from '@/api/conversations'
import { scopeKey } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { createStyles } from '@/ui/theme'
import { iconSizes } from '@/ui/tokens'
import { ChatHeader } from './ChatHeader'
import { ChatScreen } from './ChatScreen'
import { ClassicChatScreen } from './classic/ClassicChatScreen'

type ChatEntryScreenProps = ComponentProps<typeof ChatScreen> & { conversationId?: string }

export function ChatEntryScreen({ conversationId, ...props }: ChatEntryScreenProps): ReactElement {
    const styles = useStyles()
    const scope = useProjectScope()
    const mode = useDataMode()
    const explicitTask = !!props.initialTaskId || !!props.initialReportId || !!props.initialObject
    const [newChat, setNewChat] = useState(false)
    const [generation, setGeneration] = useState(0)
    const conversation = useQuery({
        queryKey: ['chat-conversation', ...scopeKey(scope), conversationId],
        queryFn: ({ signal }) => getConversation(conversationId as string, signal),
        enabled: mode === 'live' && !!scope && !!conversationId && !newChat,
        retry: false,
    })
    const detail = conversation.isFetchedAfterMount ? conversation.data : undefined
    const restart = (): void => {
        setNewChat(true)
        setGeneration((value) => value + 1)
    }
    if (mode === 'demo' || (explicitTask && !newChat))
        return (
            <ChatScreen
                key={generation}
                {...props}
                initialTaskId={newChat ? undefined : props.initialTaskId}
                initialRunId={newChat ? undefined : props.initialRunId}
                initialReportId={newChat ? undefined : props.initialReportId}
                initialObject={newChat ? null : props.initialObject}
                onNewChat={restart}
            />
        )
    if (conversationId && !newChat) {
        if (detail && (detail.agent_runtime !== 'sandbox' || detail.task)) {
            return detail.agent_runtime === 'sandbox' && detail.task ? (
                <ChatScreen {...props} initialTaskId={detail.task.id} initialRunId={undefined} onNewChat={restart} />
            ) : (
                <ClassicChatScreen
                    conversationId={conversationId}
                    initialConversation={detail}
                    source={props.source}
                    autoFocus={props.autoFocus ?? false}
                    onBack={props.onBack}
                    onNewChat={restart}
                />
            )
        }
        return (
            <View style={styles.screen}>
                {conversation.isError || detail ? (
                    <StateView
                        icon={<WarningIcon size={iconSizes.empty} />}
                        title={detail ? 'This chat is not ready yet' : "Couldn't load this chat"}
                        actionLabel="Try again"
                        onAction={() => void conversation.refetch()}
                    />
                ) : (
                    <LoadingView label="Loading chat" />
                )}
                <ChatHeader webUrl={undefined} onBack={props.onBack} onNewChat={restart} />
            </View>
        )
    }
    if (mode === 'loading' || !scope)
        return (
            <View style={styles.screen}>
                <LoadingView label="Loading chat" />
                <ChatHeader webUrl={undefined} onBack={props.onBack} onNewChat={restart} />
            </View>
        )
    return scope.host === 'https://us.posthog.com' && scope.projectId === 2 ? (
        <ChatScreen
            key={generation}
            {...props}
            initialTaskId={undefined}
            initialRunId={undefined}
            initialReportId={undefined}
            initialObject={null}
            onNewChat={restart}
        />
    ) : (
        <ClassicChatScreen
            key={generation}
            source={props.source}
            autoFocus={props.autoFocus ?? false}
            onBack={props.onBack}
            onNewChat={restart}
        />
    )
}

const useStyles = createStyles(({ colors }) => ({ screen: { flex: 1, backgroundColor: colors.surface } }))
