import type { ThreadItem } from '../types/streamTypes'

// The parts of the ticket that the writing-posthog-support-tickets skill writes. Each part starts with a
// bold label at the start of a line. Two labels carry the agent's own name, such as "What PostHog AI checked".
const TICKET_LABEL =
    /^\*\*(?:what i want|why|questions|what i tried|what [^*]{1,40} checked|[^*]{1,40} told me|left for support|links|details|error)(?::\*\*|\*\*:)/i
const TICKET_START = /^\*\*what i want(?::\*\*|\*\*:)/i
const FENCE_OPEN = /^\s*(`{3,}|~{3,})/
const LIST_LINE = /^\s*(?:[-*+]|\d+[.)])\s|^\s{2,}\S/

function isFenceClose(line: string, open: string): boolean {
    const trimmed = line.trim()
    return trimmed.length >= open.length && trimmed === open[0].repeat(trimmed.length)
}

/** Splits markdown into blocks at blank lines. A fenced code block is one block, blank lines included. */
function splitBlocks(text: string): string[][] {
    const blocks: string[][] = []
    let current: string[] = []
    let fence: string | null = null
    const flush = (): void => {
        if (current.length) {
            blocks.push(current)
            current = []
        }
    }
    for (const line of text.split('\n')) {
        if (fence) {
            current.push(line)
            if (isFenceClose(line, fence)) {
                fence = null
                flush()
            }
            continue
        }
        const open = FENCE_OPEN.exec(line)
        if (open) {
            flush()
            fence = open[1]
            current.push(line)
        } else if (line.trim()) {
            current.push(line)
        } else {
            flush()
        }
    }
    flush()
    return blocks
}

const isCodeBlock = (block: string[]): boolean => FENCE_OPEN.test(block[0])

/** A label alone on its line, such as `**Error:**`, takes the next block as its body. */
function labelAwaitsBody(block: string[]): boolean {
    return block.length === 1 && block[0].trim().replace(TICKET_LABEL, '').trim() === ''
}

/**
 * Returns the support ticket that an agent message holds, without the agent's text around it, or null.
 * A ticket in a fenced code block is returned whole. An unfenced ticket starts at its "What I want" part
 * and ends at the first plain paragraph that is not a part's body, which is where the agent's own
 * hand-off text starts.
 */
export function extractSupportTicketDraft(text: string): string | null {
    const blocks = splitBlocks(text)

    for (const block of blocks) {
        if (isCodeBlock(block)) {
            const closed = block.length > 1 && isFenceClose(block[block.length - 1], FENCE_OPEN.exec(block[0])![1])
            const inner = block.slice(1, closed ? -1 : undefined)
            const firstLine = inner.find((line) => line.trim())
            if (firstLine && TICKET_START.test(firstLine.trim())) {
                return inner.join('\n').trim()
            }
        }
    }

    const start = blocks.findIndex((block) => !isCodeBlock(block) && TICKET_START.test(block[0].trim()))
    if (start === -1) {
        return null
    }
    const ticket = [blocks[start]]
    let awaitingBody = labelAwaitsBody(blocks[start])
    for (const block of blocks.slice(start + 1)) {
        if (TICKET_LABEL.test(block[0].trim())) {
            awaitingBody = labelAwaitsBody(block)
        } else if (isCodeBlock(block) || LIST_LINE.test(block[0])) {
            awaitingBody = false
        } else if (awaitingBody) {
            awaitingBody = false
        } else {
            break
        }
        ticket.push(block)
    }
    return ticket.map((block) => block.join('\n')).join('\n\n')
}

/**
 * The most recent support ticket the agent drafted in this conversation, or null. The search stops at a
 * `/clear`, because a ticket from before it is about a conversation the person chose to drop.
 */
export function findSupportTicketDraft(threadItems: ThreadItem[]): string | null {
    for (let i = threadItems.length - 1; i >= 0; i--) {
        const item = threadItems[i]
        if (item.type === 'conversation_cleared') {
            return null
        }
        // A message that is still streaming can hold half a ticket.
        if (item.type === 'assistant_message' && item.complete !== false && item.text) {
            const draft = extractSupportTicketDraft(item.text)
            if (draft) {
                return draft
            }
        }
    }
    return null
}
