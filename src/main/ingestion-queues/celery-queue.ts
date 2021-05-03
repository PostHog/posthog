import { Queue } from '../../types'
import { Base } from '../../utils/celery/base'
import { Message } from '../../utils/celery/message'
import { status } from '../../utils/status'

type Handler = (...args: any[]) => Promise<void>

export class CeleryQueue extends Base implements Queue {
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
        status.info('🍆', 'Starting Celery worker...')
        return this.run().catch((error) =>
            status.error('⚠️', 'An error occured while starting Celery worker:\n', error)
        )
    }

    /**
     * Pause the worker. await the response to be sure all pending `processNextTick` events have finished.
     * @method Worker#pause
     */
    public pause(): Promise<void> {
        return this.broker.pause()
    }

    /**
     * Resume the worker
     * @method Worker#pause
     */
    public resume(): void {
        this.broker.resume()
    }

    /**
     * Is the worker paused
     * @method Worker#isPaused
     *
     * @returns {boolean}
     */
    public isPaused(): boolean {
        return this.broker.isPaused()
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

        return () => {
            const result = this.broker.subscribe(queue, onMessage)
            status.info('✅', `Celery worker subscribed to ${Object.keys(this.handlers).join(', ')}!`)
            return result
        }
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

            console.debug(
                `celery.node Received task: ${taskName}[${taskId}], args: ${args}, kwargs: ${JSON.stringify(kwargs)}`
            )

            const timeStart = process.hrtime()
            const taskPromise = handler(...args, kwargs).then((result) => {
                const diff = process.hrtime(timeStart)
                console.debug(
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
    public async stop(): Promise<void> {
        const taskCount = this.activeTasks.size
        if (taskCount > 0) {
            status.info(
                '⌛',
                `${taskCount} ${taskCount === 1 ? 'task' : 'tasks'} in progress, waiting for ${
                    taskCount === 1 ? 'it' : 'them'
                } to finish before disconnecting Celery...`
            )
            await this.whenCurrentJobsFinished()
        } else {
            status.info('👍', 'No tasks in progress, disconnecting Celery...')
        }
        await this.disconnect()
        status.info('🛑', 'Celery worker disconnected!')
    }
}
