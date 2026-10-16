import type { ChatSessionStatus } from '@/model/types'
import { colors } from '@/ui/tokens'

import { sessionStatusDisplay } from './sessionStatus'

describe('session status display', () => {
    test.each<[ChatSessionStatus, string, string]>([
        ['working', 'Working', colors.blue],
        ['queued', 'Queued', colors.blue],
        ['starting', 'Starting', colors.blue],
        ['failed', 'Failed', colors.orange],
        ['completed', 'Completed', colors.tertiary],
        ['stopped', 'Stopped', colors.tertiary],
        ['idle', 'Idle', colors.tertiary],
    ])('%s shows %s', (status, label, dotColor) => {
        expect(sessionStatusDisplay(status)).toEqual({ label, dotColor })
    })
})
