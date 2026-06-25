// Pure-Node ingestion perf baseline for the HogVM three-way comparison.
//
// Runs the exact same compiled program (tests/static/perf_program.json) over the exact same
// events (deterministic formula, identical to the Rust harness and the Python generator) through
// the reference TypeScript VM. Node is single-threaded by nature, so this is the baseline the
// Rust single-thread floor and the rayon-parallel / FFI modes are measured against.
//
// Build the VM first (common/hogvm/typescript: pnpm run build), then:
//   node rust/common/hogvm/benches/ingestion_node.js

const fs = require('fs')
const path = require('path')

const repoRoot = path.resolve(__dirname, '../../../..')
const { execSync } = require(path.join(repoRoot, 'common/hogvm/typescript/dist/index.js'))

const SERIES_LEN = 128 // must match gen_perf_workload.py + ingestion.rs
const TOTAL_EVENTS = 10000
const BATCH_SIZE = 2000

const program = JSON.parse(fs.readFileSync(path.join(__dirname, '../tests/static/perf_program.json')))
const oracle = JSON.parse(fs.readFileSync(path.join(__dirname, '../tests/static/perf_oracle.json')))

function makeEvent(e) {
    const series = new Array(SERIES_LEN)
    for (let i = 0; i < SERIES_LEN; i++) {
        series[i] = (e * 131 + i * 977) % 1000
    }
    return { series, k: e % 257 }
}

// Correctness gate against the reference results before trusting timings.
for (let e = 0; e < oracle.results.length; e++) {
    const got = execSync(program, { globals: makeEvent(e) })
    if (got !== oracle.results[e]) {
        throw new Error(`node diverged on event ${e}: got ${got}, expected ${oracle.results[e]}`)
    }
}
console.log(`correctness: first ${oracle.results.length} events match reference ✓`)

function runAll() {
    const out = new Array(TOTAL_EVENTS)
    for (let e = 0; e < TOTAL_EVENTS; e++) {
        out[e] = execSync(program, { globals: makeEvent(e) })
    }
    return out
}

const reps = 5
let bestMs = Infinity
for (let r = 0; r < reps; r++) {
    const t = process.hrtime.bigint()
    const out = runAll()
    const ms = Number(process.hrtime.bigint() - t) / 1e6
    if (out.length !== TOTAL_EVENTS) throw new Error('bad run')
    bestMs = Math.min(bestMs, ms)
}
const tput = TOTAL_EVENTS / (bestMs / 1000)
console.log(`\nworkload: ${TOTAL_EVENTS} events, batch ${BATCH_SIZE}, ${SERIES_LEN}-element series`)
console.log('\n================ pure-Node ingestion perf ================')
console.log(`node single : ${bestMs.toFixed(2)} ms  | ${tput.toFixed(0)} events/s`)
console.log('==========================================================')
