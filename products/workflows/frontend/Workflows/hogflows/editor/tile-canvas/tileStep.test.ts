import type { HogFlowAction } from '../../types'
import type { StepGraph } from './stepFacts'
import { tileStep } from './tileStep'

describe('tileStep', () => {
    it.each([
        ['keeps a name someone gave the step', 'Nudge trial users', 'Nudge trial users'],
        ['skips the name the step picker gave it', 'Delay', undefined],
        ['skips a name the caption already shows', 'Wait 1 hour', undefined],
        ['skips an empty name', '  ', undefined],
    ])('%s', (_, name, expected) => {
        const action = { id: 'delay', type: 'delay', name, config: { delay_duration: '1h' } } as HogFlowAction
        const workflow: StepGraph = { actions: [action], edges: [], exit_condition: 'exit_only_at_end' }

        const tile = tileStep(action, workflow, { templatesById: {}, isDarkModeOn: false, kindName: 'Delay' })

        expect(tile.customName).toBe(expected)
    })
})
