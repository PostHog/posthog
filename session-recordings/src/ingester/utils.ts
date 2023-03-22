import { PersistedRecordingMessage, IncomingRecordingMessage } from '../types'

export const convertToPersitedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: message.data,
    }
}
