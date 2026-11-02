import { useQueryClient } from '@tanstack/react-query'
import { useFocusEffect, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshControl, SectionList, View } from 'react-native'

import { useProjectScope } from '@/auth/useProjectScope'
import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { track } from '@/lib/analytics'
import { useNow } from '@/lib/useNow'
import type { ChatListItem } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { SearchField } from '@/ui/SearchField'
import { LoadingView, StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { toChatError } from '../chat/chatErrors'
import type { ChatSheetEntry } from '../chat/chatSheetEvents'
import { TABS_HEADER_BOTTOM } from '../tabs/TabsHeader'
import { useTabHeader } from '../tabs/tabHeaderStore'
import { ChatRow } from './ChatRow'
import { ChatRowMenu, type ChatRowMenuTarget } from './ChatRowMenu'
import { filterChats, groupChats } from './chatGroups'
import { sessionListKeys, useArchiveChat, useChatList } from './hooks'

interface ChatSection {
    label: string
    data: ChatListItem[]
}

function keyFor(item: ChatListItem): string {
    return item.id
}

const SEARCH_SETTLE_MS = 600

function useSearchEvent(search: string, resultCount: number): void {
    const tracked = useRef('')
    const query = search.trim()
    useEffect(() => {
        if (!query || tracked.current === query) {
            return undefined
        }
        const timer = setTimeout(() => {
            tracked.current = query
            track('mobile_chats_searched', { query_length: query.length, result_count: resultCount })
        }, SEARCH_SETTLE_MS)
        return () => clearTimeout(timer)
    }, [query, resultCount])
}

export function ChatsScreen(): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const now = useNow()
    const query = useChatList()
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    const [search, setSearch] = useState('')
    const [rowMenu, setRowMenu] = useState<ChatRowMenuTarget | null>(null)
    const toasts = useToasts()
    const archiveActions = useArchiveChat()

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

    const newChat = useCallback(() => {
        const entry: ChatSheetEntry = 'chats_empty'
        router.push({ pathname: '/chat', params: { entry } })
    }, [router])
    const searching = search.trim().length > 0
    const openChat = useCallback(
        (item: ChatListItem) => {
            const entry: ChatSheetEntry = searching ? 'chats_search' : 'chats_list'
            router.push({ pathname: '/chat', params: { taskId: item.sourceId, entry, origin: item.origin } })
        },
        [router, searching]
    )
    const openRowMenu = useCallback((item: ChatListItem, anchor: RowAnchor) => {
        track('mobile_chat_row_menu_opened', { origin: item.origin, status: item.status })
        setRowMenu({ item, anchor })
    }, [])
    const restore = (item: ChatListItem): void => {
        track('mobile_chat_archive_undone', { origin: item.origin, status: item.status })
        archiveActions.restore(item).catch((error: unknown) => {
            track('mobile_chat_archive_failed', { action: 'restore', code: toChatError(error).kind })
            toasts.show("Couldn't restore this chat. Try again.")
        })
    }
    // The row leaves at once and the toast offers Undo. A failed request brings the row back with a message.
    const archive = (item: ChatListItem): void => {
        setRowMenu(null)
        track('mobile_chat_archived', { origin: item.origin, status: item.status })
        toasts.show('Chat archived', () => restore(item))
        archiveActions.archive(item).catch((error: unknown) => {
            track('mobile_chat_archive_failed', { action: 'archive', code: toChatError(error).kind })
            toasts.show("Couldn't archive this chat. Try again.")
        })
    }
    const refresh = (trigger: 'pull' | 'retry'): void => {
        track('mobile_chats_refreshed', { trigger })
        void query.refetch()
    }
    useTabHeader('chats', {
        refreshing: query.isRefetching,
        hint: null,
        status: null,
        editing: null,
        editPins: null,
        filter: null,
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
    useSearchEvent(
        search,
        sections.reduce((count, section) => count + section.data.length, 0)
    )

    // The kind only, because a server message can name the customer's host.
    const loadErrorCode = query.isError ? toChatError(query.error).kind : null
    useEffect(() => {
        if (loadErrorCode) {
            track('mobile_chats_load_failed', { code: loadErrorCode })
        }
    }, [loadErrorCode])

    // The header floats over the list, so the content starts below it and the pull-to-refresh spinner shows under it.
    const contentTop = topOffset(insets, TABS_HEADER_BOTTOM)

    const renderItem = useCallback(
        ({ item }: { item: ChatListItem }) => (
            <ChatRow item={item} now={now} onOpen={openChat} onLongPress={openRowMenu} />
        ),
        [now, openChat, openRowMenu]
    )
    const renderSectionHeader = useCallback(
        ({ section }: { section: ChatSection }) => (
            <View style={styles.sectionHeader}>
                <Eyebrow>{section.label}</Eyebrow>
            </View>
        ),
        [styles]
    )

    const empty = query.isLoading ? (
        <LoadingView label="Loading your chats" />
    ) : query.isError ? (
        <StateView
            icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
            title="Couldn't load your chats"
            message={query.error?.message ?? 'Check your connection and try again.'}
            actionLabel="Try again"
            onAction={() => refresh('retry')}
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
    const listHeader = hasItems ? (
        <View style={styles.search}>
            <SearchField value={search} onChangeText={setSearch} placeholder="Search chats" testID="chats-search" />
        </View>
    ) : null

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
                        onRefresh={() => refresh('pull')}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={contentTop}
                    />
                }
            />
            <ChatRowMenu target={rowMenu} onClose={() => setRowMenu(null)} onArchive={archive} />
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.inboxGutter,
    },
    search: {
        marginTop: 4,
        marginBottom: 4,
    },
    sectionHeader: {
        paddingTop: 20,
        paddingBottom: 4,
        paddingHorizontal: 2,
    },
}))
