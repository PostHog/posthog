import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'

import { PluginsServerConfig } from '../types'
import { status } from './status'
import { createRedis } from './utils'

export type PubSubTask = ((message: string) => void) | ((message: string) => Promise<void>)

export interface PubSubTaskMap {
    [channel: string]: PubSubTask
}

export class PubSub {
    private serverConfig: PluginsServerConfig
    private redis: Redis | null
    public taskMap: PubSubTaskMap

    constructor(serverConfig: PluginsServerConfig, taskMap: PubSubTaskMap = {}) {
        this.serverConfig = serverConfig
        this.redis = null
        this.taskMap = taskMap
    }

    public async start(): Promise<void> {
        if (this.redis) {
            throw new Error('Started PubSub cannot be started again!')
        }
        this.redis = await createRedis(this.serverConfig)
        const channels = Object.keys(this.taskMap)
        await this.redis.subscribe(channels)
        this.redis.on('message', (channel: string, message: string) => {
            const task: PubSubTask | undefined = this.taskMap[channel]
            if (!task) {
                captureException(
                    new Error(
                        `Received a pubsub message for unassociated channel ${channel}! Associated channels are: ${Object.keys(
                            this.taskMap
                        ).join(', ')}`
                    )
                )
            }
            void task(message)
        })
        status.info('👀', `Pub-sub started for channels: ${channels.join(', ')}`)
    }

    public async stop(): Promise<void> {
        if (!this.redis) {
            throw new Error('Unstarted PubSub cannot be stopped!')
        }
        await this.redis.unsubscribe()
        this.redis.disconnect()
        this.redis = null
        status.info('🛑', `Pub-sub stopped for channels: ${Object.keys(this.taskMap).join(', ')}`)
    }
}
