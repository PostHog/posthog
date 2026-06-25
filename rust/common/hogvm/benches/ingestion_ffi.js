// Rust-from-Node (napi-rs FFI) ingestion perf — the realistic production shape.
//
// Node generates the event batch, hands it across the FFI boundary to the Rust binding, which runs
// the same compiled program over all events on its own rayon thread pool and returns the results.
// This measures the production trade-off: native parallelism vs the cost of marshalling the batch
// across the boundary. Same program + same event formula as the pure-Node and pure-Rust harnesses.
//
// Build the binding first: rust/common/hogvm/scripts/run_ffi.sh (which also runs this).

const fs = require('fs')
const path = require('path')

const binding = require(path.join(__dirname, '../node/hogvm-node.node'))

const SERIES_LEN = 128 // must match the other harnesses
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

const allEvents = new Array(TOTAL_EVENTS)
for (let e = 0; e < TOTAL_EVENTS; e++) {
    allEvents[e] = makeEvent(e)
}

// Correctness gate against the reference results.
const sample = allEvents.slice(0, oracle.results.length)
const sres = binding.executeBatch(program, sample, true)
for (let e = 0; e < oracle.results.length; e++) {
    if (sres[e] !== oracle.results[e]) {
        throw new Error(`ffi diverged on event ${e}: got ${sres[e]}, expected ${oracle.results[e]}`)
    }
}
console.log(`correctness: first ${oracle.results.length} events match reference ✓`)

const reps = 5
function bestMs(parallel) {
    let best = Infinity
    for (let r = 0; r < reps; r++) {
        const t = process.hrtime.bigint()
        const out = binding.executeBatch(program, allEvents, parallel)
        const ms = Number(process.hrtime.bigint() - t) / 1e6
        if (out.length !== TOTAL_EVENTS) throw new Error('bad run')
        best = Math.min(best, ms)
    }
    return best
}

// Single-threaded FFI isolates the boundary-marshalling cost (same 1-core execution as in-process
// "single", plus the napi serde round-trip); parallel FFI adds rayon on top of that same cost.
const singleMs = bestMs(false)
const parallelMs = bestMs(true)
const cores = require('os').cpus().length
const tput = (ms) => TOTAL_EVENTS / (ms / 1000)

console.log(`\nworkload: ${TOTAL_EVENTS} events, batch ${BATCH_SIZE}, ${SERIES_LEN}-element series | cores: ${cores}`)
console.log('\n============ Rust-from-Node (napi-rs FFI) ingestion perf ============')
console.log(`ffi single   : ${singleMs.toFixed(2)} ms  | ${tput(singleMs).toFixed(0)} events/s  (1 core + boundary marshalling)`)
console.log(`ffi parallel : ${parallelMs.toFixed(2)} ms  | ${tput(parallelMs).toFixed(0)} events/s  (${cores} cores + boundary marshalling)`)
console.log('====================================================================')
