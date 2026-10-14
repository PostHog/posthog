import { nextTaskTitle } from './task-title'

describe('nextTaskTitle', () => {
    test.each([
        ['saves a new title', 'Fix the export', 'Old title', 'Fix the export'],
        ['trims surrounding whitespace', '  Fix the export  ', 'Old title', 'Fix the export'],
        ['skips a blank title', '', 'Old title', null],
        ['skips a whitespace-only title', '   ', 'Old title', null],
        ['skips an unchanged title', 'Old title', 'Old title', null],
        ['skips a title that only gained whitespace', '  Old title  ', 'Old title', null],
        ['saves over a task that has no title yet', 'Fix the export', undefined, 'Fix the export'],
    ])('%s', (_name, input, currentTitle, expected) => {
        expect(nextTaskTitle(input, currentTitle)).toBe(expected)
    })
})
