import { useQuery } from '@tanstack/react-query'
import { type ComponentProps, type ReactElement, useState } from 'react'
import { View } from 'react-native'

import { getChatRuntime, getConversation } from '@/api/conversations'
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
    const explicitTask = !!props.initialTaskId || !!props.initialReportId || !!props.initialObject || mode === 'demo'
    const [newChat, setNewChat] = useState(false)
    const [revision, setRevision] = useState(0)
    const [selected, setSelected] = useState<'langgraph' | 'sandbox' | null>(null)
    const conversation = useQuery({
        queryKey: ['chat-conversation', ...scopeKey(scope), conversationId],
        queryFn: ({ signal }) => getConversation(conversationId as string, signal),
        enabled: mode === 'live' && !!scope && !!conversationId && !newChat,
        retry: false,
    })
    const runtime = useQuery({
        queryKey: ['chat-runtime', ...scopeKey(scope), revision],
        queryFn: ({ signal }) => getChatRuntime(signal),
        enabled: mode === 'live' && !!scope && (!explicitTask || newChat) && (!conversationId || newChat),
        staleTime: 0,
        retry: false,
    })
    const restart = (): void => {
        setNewChat(true)
        setSelected(null)
        setRevision((value) => value + 1)
    }
    if (explicitTask && !newChat) return <ChatScreen {...props} onNewChat={restart} />
    if (conversationId && !newChat) {
        if (conversation.data && (conversation.data.agent_runtime !== 'sandbox' || conversation.data.task)) {
            return conversation.data.agent_runtime === 'sandbox' && conversation.data.task ? (
                <ChatScreen
                    {...props}
                    initialTaskId={conversation.data.task.id}
                    initialRunId={undefined}
                    onNewChat={restart}
                />
            ) : (
                <ClassicChatScreen
                    conversationId={conversationId}
                    source={props.source}
                    autoFocus={props.autoFocus ?? false}
                    onBack={props.onBack}
                    onNewChat={restart}
                />
            )
        }
        return (
            <View style={styles.screen}>
                {conversation.isError || conversation.data ? (
                    <StateView
                        icon={<WarningIcon size={iconSizes.empty} />}
                        title={conversation.data ? 'This chat is not ready yet' : "Couldn't load this chat"}
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
    const resolved =
        runtime.isFetchedAfterMount && !runtime.isFetching
            ? runtime.isError
                ? 'langgraph'
                : (runtime.data ?? null)
            : null
    if (!selected && resolved) setSelected(resolved)
    const active = selected ?? resolved
    if (!active && !runtime.isError)
        return (
            <View style={styles.screen}>
                <LoadingView label="Loading chat" />
                <ChatHeader webUrl={undefined} onBack={props.onBack} onNewChat={restart} />
            </View>
        )
    return active === 'sandbox' ? (
        <ChatScreen
            {...props}
            initialTaskId={undefined}
            initialRunId={undefined}
            initialReportId={undefined}
            initialObject={null}
            onNewChat={restart}
        />
    ) : (
        <ClassicChatScreen
            source={props.source}
            autoFocus={props.autoFocus ?? false}
            onBack={props.onBack}
            onNewChat={restart}
        />
    )
}

const useStyles = createStyles(({ colors }) => ({ screen: { flex: 1, backgroundColor: colors.surface } }))
