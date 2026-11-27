import { healthLabelGroups } from './healthChartLabels'

describe('healthChartLabels', () => {
    test.each([
        { name: 'labels every position far enough apart', positions: [0, 30, 60], expected: [[0], [1], [2]] },
        {
            name: 'puts positions too close to label apart under one label',
            positions: [0, 3, 6],
            expected: [[0, 1, 2]],
        },
        {
            name: 'measures the gap from the last label, not the last position',
            positions: [0, 15, 30],
            expected: [[0, 1], [2]],
        },
    ])('healthLabelGroups: $name', ({ positions, expected }) => {
        expect(healthLabelGroups(positions, 22)).toEqual(expected)
    })
})
