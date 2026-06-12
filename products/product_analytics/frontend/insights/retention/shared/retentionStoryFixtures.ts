// Realistic retention curve fixture shared across retention chart stories
const retentionCurve = [1.0, 0.58, 0.42, 0.32, 0.26, 0.22, 0.18, 0.15]
const cohortSeeds = [1024, 1150, 980, 870, 1320, 1080, 940, 760]

export const realisticRetentionResult = cohortSeeds.map((seed, cohortIndex) => {
    const periodCount = Math.max(1, cohortSeeds.length - cohortIndex)
    const jitter = 1 + ((cohortIndex % 3) - 1) * 0.04
    return {
        label: `Day ${cohortIndex}`,
        date: `2023-07-${String(cohortIndex + 1).padStart(2, '0')}T00:00:00Z`,
        values: retentionCurve.slice(0, Math.min(periodCount, retentionCurve.length)).map((r, i) => ({
            count: i === 0 ? seed : Math.round(seed * r * jitter),
            people: [],
        })),
        people_url: '',
    }
})
