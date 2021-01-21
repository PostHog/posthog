import { threadId } from 'worker_threads'

export type StatusMethod = (icon: string, ...message: any[]) => void

export interface Status {
    info: StatusMethod
    error: StatusMethod
}

function getPrefix(): string {
    return `[${threadId ? threadId.toString().padStart(4, '_') : 'MAIN'}]`
}

export const status: Status = {
    info(icon: string, ...message: any[]) {
        console.info(getPrefix(), icon, ...message.filter(Boolean))
    },
    error(icon: string, ...message: any[]) {
        console.error(getPrefix(), icon, ...message.filter(Boolean))
    },
}
