/**
 * writes here Base Parent class of Celery client and worker
 * @author SunMyeong Lee <actumn814@gmail.com>
 */
import { DB } from '../db/db'
import { Broker } from './broker'
import { CeleryConf, defaultConf } from './conf'

export class Base {
    broker: Broker
    conf: CeleryConf
    db: DB

    /**
     * Parent Class of Client and Worker
     * for creates an instance of celery broker and celery backend
     *
     * @constructor Base
     */
    constructor(db: DB, queue = 'celery') {
        this.db = db
        this.conf = defaultConf()
        this.conf.CELERY_QUEUE = queue
        this.broker = new Broker(db)
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
