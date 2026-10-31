import { runningExperimentId } from './runningExperimentId'

describe('runningExperimentId', () => {
    it.each([
        { case: 'no experiment', metadata: null, expected: null },
        {
            case: 'a draft or completed experiment',
            metadata: [{ id: 7, name: 'A', is_running: false }],
            expected: null,
        },
        {
            case: 'a running experiment among others',
            metadata: [
                { id: 7, name: 'A', is_running: false },
                { id: 8, name: 'B', is_running: true },
            ],
            expected: 8,
        },
    ])('is $expected for a flag with $case', ({ metadata, expected }) => {
        expect(runningExperimentId({ experiment_set_metadata: metadata })).toBe(expected)
    })
})
