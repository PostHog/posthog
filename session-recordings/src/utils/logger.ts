import pino, { Logger } from 'pino'
import { config } from '../config'

export const createLogger = (name: string): Logger => {
    return pino({ name, level: config.logLevel || 'info' })
}
