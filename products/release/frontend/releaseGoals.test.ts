import type { MetricGoalApi } from './generated/api.schemas'
import { goalStatus } from './releaseGoals'

const atLeast: MetricGoalApi = { insight_id: 1, direction: 'at_least', value: 100 }
const atMost: MetricGoalApi = { insight_id: 1, direction: 'at_most', value: 2 }

describe('goalStatus', () => {
    it.each([
        { name: 'no goal', value: 50, goal: undefined, expected: 'no_goal' },
        { name: 'no value yet', value: null, goal: atLeast, expected: 'unmeasured' },
        { name: 'reaching an at least goal meets it', value: 100, goal: atLeast, expected: 'met' },
        { name: 'seventy percent of an at least goal is on track', value: 70, goal: atLeast, expected: 'on_track' },
        { name: 'less than that is behind', value: 69, goal: atLeast, expected: 'behind' },
        { name: 'staying under an at most goal meets it', value: 1.5, goal: atMost, expected: 'met' },
        { name: 'a little over an at most goal is on track', value: 2.5, goal: atMost, expected: 'on_track' },
        { name: 'far over an at most goal is behind', value: 4, goal: atMost, expected: 'behind' },
    ])('$name', ({ value, goal, expected }) => {
        expect(goalStatus(value, goal)).toBe(expected)
    })
})
