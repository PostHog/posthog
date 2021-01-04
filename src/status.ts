import { threadId } from 'worker_threads'

export type StatusMethod = ((emoji: string, message: string) => void) | ((message: string) => void)

export interface Status {
    info: StatusMethod
    error: StatusMethod
}

function transform(emojiOrMessage: string, message?: string): string {
    return `[${threadId ? threadId.toString().padStart(4, '_') : 'MAIN'}] ${[emojiOrMessage, message]
        .filter(Boolean)
        .join(' ')}`
}

export const status: Status = {
    info(emojiOrMessage: string, message?: string) {
        console.info(transform(emojiOrMessage, message))
    },
    error(emojiOrMessage: string, message?: string) {
        console.error(transform(emojiOrMessage, message))
    },
}
