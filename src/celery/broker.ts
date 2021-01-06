import * as Redis from 'ioredis'
import { v4 } from 'uuid'
import { Pausable } from '../types'
import { Message } from './message'

type BrokerSubscription = { queue: string; callback: (message: Message) => any }

class RedisMessage extends Message {
    private raw: Record<string, any>

    constructor(payload: Record<string, any>) {
        super(
            Buffer.from(payload['body'], 'base64'),
            payload['content-type'],
            payload['content-encoding'],
            payload['properties'],
            payload['headers']
        )

        this.raw = payload
    }
}

export default class RedisBroker implements Pausable {
    redis: Redis.Redis
    subscriptions: BrokerSubscription[] = []
    channels: Promise<void>[] = []
    closing = false
    paused = false

    /**
     * Redis broker class
     * @constructor RedisBroker
     * @param {string} url the connection string of redis
     * @param {object} opts the options object for redis connect of ioredis
     */
    constructor(redis: Redis.Redis) {
        this.redis = redis
    }

    /**
     * @method RedisBroker#disconnect
     * @returns {Promise} promises that continues if redis disconnected.
     */
    public disconnect(): Promise<any> {
        this.closing = true
        return Promise.all(this.channels)
    }

    /**
     * @method RedisBroker#publish
     *
     * @returns {Promise}
     */
    public publish(
        body: Record<string, any> | [Array<any>, Record<string, any>, Record<string, any>],
        exchange: string,
        routingKey: string,
        headers: Record<string, any>,
        properties: Record<string, any>
    ): Promise<number> {
        const messageBody = JSON.stringify(body)
        const contentType = 'application/json'
        const contentEncoding = 'utf-8'
        const message = {
            body: Buffer.from(messageBody).toString('base64'),
            'content-type': contentType,
            'content-encoding': contentEncoding,
            headers,
            properties: {
                body_encoding: 'base64',
                delivery_info: {
                    exchange: exchange,
                    routing_key: routingKey,
                },
                delivery_mode: 2,
                delivery_tag: v4(),
                ...properties,
            },
        }

        return this.redis.lpush(routingKey, JSON.stringify(message))
    }

    /**
     * Pause execution of queue. Wait until all channel promises have been exhausted.
     * @method RedisBroker#pause
     *
     * @returns {Promise}
     */
    public async pause(): Promise<void> {
        if (this.paused) {
            return
        }
        const oldChannels = this.channels
        this.paused = true
        this.channels = []
        await Promise.all(oldChannels)
    }

    public resume(): void {
        if (!this.paused) {
            return
        }
        this.paused = false
        for (const { queue, callback } of this.subscriptions) {
            this.channels.push(new Promise((resolve) => this.receiveFast(resolve, queue, callback)))
        }
    }

    public isPaused(): boolean {
        return this.paused
    }

    /**
     * @method RedisBroker#subscribe
     * @param {string} queue
     * @param {Function} callback
     * @returns {Promise}
     */
    public subscribe(queue: string, callback: (message: Message) => any): Promise<any[]> {
        this.subscriptions.push({ queue, callback })
        this.channels.push(new Promise((resolve) => this.receiveFast(resolve, queue, callback)))
        return Promise.all(this.channels)
    }

    /**
     * Ask for the next event the next chance we get.
     * @private
     * @param {Fucntion} resolve
     * @param {string} queue
     * @param {Function} callback
     */
    private receiveFast(resolve: () => void, queue: string, callback: (message: Message) => any): void {
        process.nextTick(() => this.recieveOneOnNextTick(resolve, queue, callback))
    }

    /**
     * Pause 50ms before asking for another event. Used if no event was returned the last time.
     * @private
     * @param {Fucntion} resolve
     * @param {string} queue
     * @param {Function} callback
     */
    private receiveSlow(resolve: () => void, queue: string, callback: (message: Message) => any): void {
        setTimeout(() => this.recieveOneOnNextTick(resolve, queue, callback), 50)
    }

    /**
     * @private
     * @param {Function} resolve
     * @param {String} queue
     * @param {Function} callback
     * @returns {Promise}
     */
    private async recieveOneOnNextTick(
        resolve: () => void,
        queue: string,
        callback: (message: Message) => any
    ): Promise<void> {
        if (this.closing || this.paused) {
            resolve()
            return
        }

        return this.receiveOne(queue)
            .then((body) => {
                if (body) {
                    callback(body)
                }
                return body
            })
            .then((body) => {
                if (body) {
                    this.receiveFast(resolve, queue, callback)
                } else {
                    this.receiveSlow(resolve, queue, callback)
                }
            })
            .catch((err) => console.error(err))
    }

    /**
     * @private
     * @param {string} queue
     * @return {Promise}
     */
    private async receiveOne(queue: string): Promise<Message | null> {
        return this.redis.brpop(queue, '5').then((result) => {
            if (!result || !result[1]) {
                return null
            }

            const [queue, item] = result
            const rawMsg = JSON.parse(item)

            // now supports only application/json of content-type
            if (rawMsg['content-type'] !== 'application/json') {
                throw new Error(`queue ${queue} item: unsupported content type ${rawMsg['content-type']}`)
            }
            // now supports only base64 of body_encoding
            if (rawMsg.properties.body_encoding !== 'base64') {
                throw new Error(`queue ${queue} item: unsupported body encoding ${rawMsg.properties.body_encoding}`)
            }
            // now supports only utf-8 of content-encoding
            if (rawMsg['content-encoding'] !== 'utf-8') {
                throw new Error(`queue ${queue} item: unsupported content encoding ${rawMsg['content-encoding']}`)
            }

            return new RedisMessage(rawMsg)
        })
    }
}
