import { threadId } from 'worker_threads'

export type StatusMethod = (icon: string, ...message: any[]) => void

export interface StatusBlueprint {
    info: StatusMethod
    warn: StatusMethod
    error: StatusMethod
}

export class Status implements StatusBlueprint {
    prefixOverride?: string

    constructor(prefixOverride?: string) {
        this.prefixOverride = prefixOverride
    }

    info(icon: string, ...message: any[]): void {
        console.info(this.getPrefix(), icon, ...message.filter(Boolean))
    }

    warn(icon: string, ...message: any[]): void {
        console.warn(this.getPrefix(), icon, ...message.filter(Boolean))
    }

    error(icon: string, ...message: any[]): void {
        console.error(this.getPrefix(), icon, ...message.filter(Boolean))
    }

    getPrefix(): string {
        return `[${this.prefixOverride ?? (threadId ? threadId.toString().padStart(4, '_') : 'MAIN')}]`
    }
}

export const status = new Status()
