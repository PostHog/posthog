import { useQueryClient } from '@tanstack/react-query'
import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useMemo, useRef, useState } from 'react'
import { RefreshControl, SectionList, StyleSheet, View } from 'react-native'

import { useProjectScope } from '@/auth/useProjectScope'
import { track } from '@/lib/analytics'
import { useNow } from '@/lib/useNow'
import type { ChatListItem } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { colors, iconSizes, layout } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { TABS_HEADER_BOTTOM } from '../tabs/TabsHeader'
import { useTabHeader } from '../tabs/tabHeaderStore'
import { ChatRow } from './ChatRow'
import { ChatsSearchField } from './ChatsSearchField'
import { filterChats, groupChats } from './chatGroups'
import { sessionListKeys, useChatList } from './hooks'

interface ChatSection {
    label: string
    data: ChatListItem[]
}

function keyFor(item: ChatListItem): string {
    return item.id
}

export function ChatsScreen(): ReactElement {
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const query = useChatList()
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    const [search, setSearch] = useState('')

    // Closing the chat sheet refocuses this screen. Invalidating instead of refetching keeps the pull spinner hidden.
    // The first focus is the mount, where the queries already fetch, so invalidating there would restart them.
    const focusedBefore = useRef(false)
    useFocusEffect(
        useCallback(() => {
            if (!focusedBefore.current) {
                focusedBefore.current = true
                return
            }
            if (scope) {
                void queryClient.invalidateQueries({ queryKey: sessionListKeys.all(scope) })
            }
        }, [queryClient, scope])
    )

    const newChat = useCallback(() => router.push('/chat'), [router])
    const openChat = useCallback(
        (item: ChatListItem) => {
            track('mobile_chat_opened', { origin: item.origin })
            router.push({ pathname: '/chat', params: { taskId: item.sourceId } })
        },
        [router]
    )
    const refresh = (): void => {
        void query.refetch()
    }
    useTabHeader('chats', {
        refresh: { state: query.isRefetching ? 'busy' : 'idle', onPress: refresh },
        status: null,
        editing: null,
        editPins: null,
    })

    const hasItems = (query.data?.length ?? 0) > 0
    const sections = useMemo<ChatSection[]>(
        () =>
            groupChats(filterChats(query.data ?? [], search), now).map((group) => ({
                label: group.label,
                data: group.items,
            })),
        [query.data, search, now]
    )

    // The header floats over the list, so the content starts below it and the pull-to-refresh spinner shows under it.
    const contentTop = topOffset(insets, TABS_HEADER_BOTTOM)

    const renderItem = useCallback(
        ({ item }: { item: ChatListItem }) => <ChatRow item={item} now={now} onOpen={openChat} />,
        [now, openChat]
    )
    const renderSectionHeader = useCallback(
        ({ section }: { section: ChatSection }) => (
            <View style={styles.sectionHeader}>
                <Eyebrow>{section.label}</Eyebrow>
            </View>
        ),
        []
    )

    const empty = query.isLoading ? (
        <LoadingView label="Loading your chats" />
    ) : query.isError ? (
        <StateView
            icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
            title="Couldn't load your chats"
            message={query.error?.message ?? 'Check your connection and try again.'}
            actionLabel="Try again"
            onAction={refresh}
            testID="chats-error"
        />
    ) : hasItems ? (
        <StateView
            icon={<SearchIcon size={iconSizes.empty} color={colors.tertiary} />}
            title="No matches"
            message="No chat titles contain that text."
            actionLabel="Clear search"
            onAction={() => setSearch('')}
            testID="chats-no-matches"
        />
    ) : (
        <StateView
            icon={<ChatBubbleIcon size={iconSizes.empty} color={colors.tertiary} />}
            title="No chats yet"
            message="Chats you start show up here. Start one with New chat."
            actionLabel="New chat"
            onAction={newChat}
            testID="chats-empty"
        />
    )

    // An element, not a component, so typing does not remount the field and drop the keyboard.
    const listHeader = hasItems ? <ChatsSearchField value={search} onChangeText={setSearch} /> : null

    return (
        <View style={styles.screen} testID="chats-screen">
            <SectionList
                sections={sections}
                keyExtractor={keyFor}
                renderItem={renderItem}
                renderSectionHeader={renderSectionHeader}
                stickySectionHeadersEnabled={false}
                ListHeaderComponent={listHeader}
                ListEmptyComponent={empty}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                contentContainerStyle={[
                    styles.content,
                    { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 120) },
                ]}
                refreshControl={
                    <RefreshControl
                        refreshing={query.isRefetching}
                        onRefresh={refresh}
                        tintColor={colors.tertiary}
                        progressViewOffset={contentTop}
                    />
                }
            />
        </View>
    )
}

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.inboxGutter,
    },
    sectionHeader: {
        paddingTop: 20,
        paddingBottom: 4,
        paddingHorizontal: 2,
    },
})
