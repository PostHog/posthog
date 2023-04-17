import { decompressFromString } from '../utils/compression'
import { PersistedRecordingMessage, IncomingRecordingMessage } from '../types'

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: decompressFromString(message.data),
    }
}
