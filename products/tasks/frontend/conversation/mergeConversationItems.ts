import type { ConversationItem } from './buildConversationItems'

type QueuedItem = Extract<ConversationItem, { type: 'queued' }>

interface MergeConversationItemsArgs {
    conversationItems: ConversationItem[]
    optimisticItems: ConversationItem[]
    queuedItems: QueuedItem[]
    isCloud: boolean
}

// Cloud's initial optimistic is pinned to the top so the user's prompt stays
// visible above setup progress. Follow-up optimistics render at the tail until
// the streamed `session/prompt` arrives and replaces them.
//
// Local sessions keep optimistic at the chronological end — they rely on
// `replaceOptimisticWithEvent` to swap optimistic↔real in place.
export function mergeConversationItems({
    conversationItems,
    optimisticItems,
    queuedItems,
    isCloud,
}: MergeConversationItemsArgs): ConversationItem[] {
    if (!isCloud) {
        const result: ConversationItem[] = [...conversationItems, ...optimisticItems]
        return queuedItems.length > 0 ? [...result, ...queuedItems] : result
    }

    const pinnedOptimisticItems = optimisticItems.filter(
        (item) => item.type !== 'user_message' || item.pinToTop !== false
    )
    const tailOptimisticItems = optimisticItems.filter(
        (item) => item.type === 'user_message' && item.pinToTop === false
    )
    const pinnedOptimisticUserContents = new Set(
        pinnedOptimisticItems
            .filter((item): item is Extract<typeof item, { type: 'user_message' }> => item.type === 'user_message')
            .map((item) => item.content)
    )
    const dedupedConversation =
        pinnedOptimisticUserContents.size === 0
            ? conversationItems
            : conversationItems.filter((item) => {
                  if (item.type !== 'user_message') {
                      return true
                  }
                  return !pinnedOptimisticUserContents.has(item.content)
              })
    const result: ConversationItem[] = [...pinnedOptimisticItems, ...dedupedConversation, ...tailOptimisticItems]
    return queuedItems.length > 0 ? [...result, ...queuedItems] : result
}
