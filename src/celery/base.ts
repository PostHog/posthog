/**
 * writes here Base Parent class of Celery client and worker
 * @author SunMyeong Lee <actumn814@gmail.com>
 */
import { CeleryConf, defaultConf } from './conf'
import RedisBroker from './broker'
import * as Redis from 'ioredis'

export default class Base {
    broker: RedisBroker
    conf: CeleryConf
    redis: Redis.Redis

    /**
     * Parent Class of Client and Worker
     * for creates an instance of celery broker and celery backend
     *
     * @constructor Base
     */
    constructor(redis: Redis.Redis, queue = 'celery') {
        this.redis = redis
        this.conf = defaultConf()
        this.conf.CELERY_QUEUE = queue
        this.broker = new RedisBroker(this.redis)
    }

    /**
     * returns promise for working some job after backend and broker ready.
     * @method Base#disconnect
     *
     * @returns {Promise} promises that continues if backend and broker disconnected.
     */
    public disconnect(): Promise<any> {
        return this.broker.disconnect()
    }
}
