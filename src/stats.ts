const sampleCount = 1000
const histories = new Map<string, Array<number>>()
const historyIndex = new Map<string, number>()

export function logTime(name: string, time: number, error?: boolean): void {
    const ms = Math.round(time * 1000) / 1000
    // TODO: add this back with better dev logging. Disabling since this trashes performance tests.
    // console.log(`Running plugin ${name}: ${error ? 'ERROR IN ' : ''}${ms}ms`)
    if (!histories.has(name)) {
        histories.set(name, new Array(sampleCount))
        historyIndex.set(name, -1)
    }
    const index = (historyIndex.get(name)! + 1) % sampleCount
    historyIndex.set(name, index)
    histories.get(name)![index] = time
}

process.on('SIGINT', () => {
    for (const [name, samples] of histories) {
        const usefulSamples = samples.filter((s) => typeof s !== 'undefined')
        console.log(`Stats for ${name}`)
        console.log(`- Count: ${usefulSamples.length}.`)
        console.log(`- Average: ${usefulSamples.reduce((a, b) => a + b) / usefulSamples.length}ms`)
        console.log(`- 50th: ${quantile(usefulSamples, 0.5)}ms`)
        console.log(`- 90th: ${quantile(usefulSamples, 0.9)}ms`)
        console.log(`- 99th: ${quantile(usefulSamples, 0.99)}ms`)
        console.log('')
    }
})

// sort array ascending
const asc = (arr: number[]) => arr.sort((a, b) => a - b)

const sum = (arr: number[]) => arr.reduce((a, b) => a + b, 0)

const mean = (arr: number[]) => sum(arr) / arr.length

// sample standard deviation
const std = (arr: number[]) => {
    const mu = mean(arr)
    const diffArr = arr.map((a) => (a - mu) ** 2)
    return Math.sqrt(sum(diffArr) / (arr.length - 1))
}

const quantile = (arr: number[], q: number) => {
    const sorted = asc(arr)
    const pos = (sorted.length - 1) * q
    const base = Math.floor(pos)
    const rest = pos - base
    if (sorted[base + 1] !== undefined) {
        return sorted[base] + rest * (sorted[base + 1] - sorted[base])
    } else {
        return sorted[base]
    }
}
