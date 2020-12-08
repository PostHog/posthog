import * as Redis from 'ioredis'
import { v4 } from 'uuid'
import { Message } from './message'

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

export default class RedisBroker {
    redis: Redis.Redis
    channels: Promise<void>[] = []
    closing = false

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
     * @method RedisBroker#subscribe
     * @param {string} queue
     * @param {Function} callback
     * @returns {Promise}
     */
    public subscribe(queue: string, callback: (message: Message) => any): Promise<any[]> {
        const promiseCount = 1

        for (let index = 0; index < promiseCount; index += 1) {
            this.channels.push(new Promise((resolve) => this.receive(index, resolve, queue, callback)))
        }

        return Promise.all(this.channels)
    }

    /**
     * @private
     * @param {number} index
     * @param {Fucntion} resolve
     * @param {string} queue
     * @param {Function} callback
     */
    private receive(index: number, resolve: () => void, queue: string, callback: (message: Message) => any): void {
        process.nextTick(() => this.recieveOneOnNextTick(index, resolve, queue, callback))
    }

    /**
     * @private
     * @param {number} index
     * @param {Function} resolve
     * @param {String} queue
     * @param {Function} callback
     * @returns {Promise}
     */
    private async recieveOneOnNextTick(
        index: number,
        resolve: () => void,
        queue: string,
        callback: (message: Message) => any
    ): Promise<void> {
        if (this.closing) {
            resolve()
            return
        }

        return this.receiveOne(queue)
            .then((body) => {
                if (body) {
                    callback(body)
                }
                Promise.resolve()
            })
            .then(() => this.receive(index, resolve, queue, callback))
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
