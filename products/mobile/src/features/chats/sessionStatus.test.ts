import type { ChatSessionStatus } from '@/model/types'
import { lightColors as colors } from '@/ui/theme'

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
        expect(sessionStatusDisplay(status, colors)).toEqual({ label, dotColor })
    })
})
