import Base from './base'
import { Message } from './message'

type Handler = (...args: any[]) => Promise<void>

export default class Worker extends Base {
    handlers: Record<string, Handler> = {}
    activeTasks: Set<Promise<any>> = new Set()

    /**
     * register task handler on worker handlers
     * @method Worker#register
     * @param {String} name the name of task for dispatching.
     * @param {Function} handler the function for task handling
     *
     * @example
     * worker.register('tasks.add', (a, b) => a + b);
     * worker.start();
     */
    public register(name: string, handler: Handler): void {
        if (!handler) {
            throw new Error('Undefined handler')
        }
        if (this.handlers[name]) {
            throw new Error('Already handler setted')
        }

        this.handlers[name] = function registHandler(...args: any[]): Promise<any> {
            try {
                return Promise.resolve(handler(...args))
            } catch (err) {
                return Promise.reject(err)
            }
        }
    }

    /**
     * start celery worker to run
     * @method Worker#start
     * @example
     * worker.register('tasks.add', (a, b) => a + b);
     * worker.start();
     */
    public start(): Promise<any> {
        console.info('celery.node worker start...')
        console.info(`registed task: ${Object.keys(this.handlers)}`)
        return this.run().catch((err) => console.error(err))
    }

    /**
     * @method Worker#run
     * @private
     *
     * @returns {Promise}
     */
    private run(): Promise<any> {
        return this.processTasks()
    }

    /**
     * @method Worker#processTasks
     * @private
     *
     * @returns function results
     */
    private processTasks(): Promise<any> {
        const consumer = this.getConsumer(this.conf.CELERY_QUEUE)
        return consumer()
    }

    /**
     * @method Worker#getConsumer
     * @private
     *
     * @param {String} queue queue name for task route
     */
    private getConsumer(queue: string): () => any {
        const onMessage = this.createTaskHandler()

        return () => this.broker.subscribe(queue, onMessage)
    }

    public createTaskHandler(): (message: Message) => any {
        const onTaskReceived = (message: Message): any => {
            if (!message) {
                return Promise.resolve()
            }

            let payload: Record<string, any> | null = null
            let taskName = message.headers['task']
            if (!taskName) {
                // protocol v1
                payload = message.decode()
                taskName = payload['task']
            }

            // strategy
            let body
            let headers
            if (payload == null && !('args' in message.decode())) {
                body = message.decode() // message.body;
                headers = message.headers
            } else if (payload) {
                const args = payload['args'] || []
                const kwargs = payload['kwargs'] || {}
                const embed = {
                    callbacks: payload['callbacks'],
                    errbacks: payload['errbacks'],
                    chord: payload['chord'],
                    chain: null,
                }

                body = [args, kwargs, embed]
                headers = {
                    lang: payload['lang'],
                    task: payload['task'],
                    id: payload['id'],
                    rootId: payload['root_id'],
                    parantId: payload['parentId'],
                    group: payload['group'],
                    meth: payload['meth'],
                    shadow: payload['shadow'],
                    eta: payload['eta'],
                    expires: payload['expires'],
                    retries: payload['retries'] || 0,
                    timelimit: payload['timelimit'] || [null, null],
                    kwargsrepr: payload['kwargsrepr'],
                    origin: payload['origin'],
                }
            }

            // request
            const [args, kwargs /*, embed */] = body as [Array<any>, Record<string, any>, Record<string, any>]
            const taskId = headers ? headers['id'] : null

            const handler = this.handlers[taskName]
            if (!handler) {
                throw new Error(`Missing process handler for task ${taskName}`)
            }

            console.info(
                `celery.node Received task: ${taskName}[${taskId}], args: ${args}, kwargs: ${JSON.stringify(kwargs)}`
            )

            const timeStart = process.hrtime()
            const taskPromise = handler(...args, kwargs).then((result) => {
                const diff = process.hrtime(timeStart)
                console.info(
                    `celery.node Task ${taskName}[${taskId}] succeeded in ${diff[0] + diff[1] / 1e9}s: ${result}`
                )
                this.activeTasks.delete(taskPromise)
            })

            // record the executing task
            this.activeTasks.add(taskPromise)

            return taskPromise
        }

        return onTaskReceived
    }

    /**
     * @method Worker#whenCurrentJobsFinished
     *
     * @returns Promise that resolves when all jobs are finished
     */
    public async whenCurrentJobsFinished(): Promise<any[]> {
        return Promise.all(Array.from(this.activeTasks))
    }

    /**
     * @method Worker#stop
     *
     * @todo implement here
     */
    // eslint-disable-next-line class-methods-use-this
    public async stop(): Promise<void> {
        const taskCount = this.activeTasks.size
        if (taskCount > 0) {
            console.log(`In progress: ${taskCount} tasks. Waiting for them to finish.`)
            await this.whenCurrentJobsFinished()
            console.log(`Finished. Shutting down celery worker.`)
        } else {
            console.log(`No tasks in progress, shutting down celery worker`)
        }

        this.disconnect()
    }
}
