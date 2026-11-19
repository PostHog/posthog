// Run from the repository root: NODE_PATH=nodejs/node_modules node rust/logs-ingestion/scripts/node-decode-reference.js
const avro = require('avsc')
const { compress, decompress } = require('@mongodb-js/zstd')
const { Readable } = require('stream')
const { createHash } = require('crypto')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '../../..')
const scenarioDir = path.join(root, 'nodejs/src/logs/parity/fixtures/scenarios')
const outFile = path.join(__dirname, '../tests/fixtures/input-decodes.json')

// Same codec registration as `decodeLogRecords` in nodejs/src/logs/log-record-avro.ts.
function decode(buffer) {
    return new Promise((resolve, reject) => {
        const records = []
        const decoder = new avro.streams.BlockDecoder({
            codecs: { zstandard: (buf, cb) => decompress(buf).then((inflated) => cb(null, inflated)).catch(cb) },
        })
        const stream = new Readable()
        stream.on('error', reject)
        stream.push(buffer)
        stream.push(null)
        stream.pipe(decoder)
        let type
        let codec = 'null'
        decoder.on('metadata', (t, c) => {
            type = t
            codec = c || 'null'
        })
        decoder.on('data', (r) => records.push(r))
        decoder.on('end', () => (type === undefined ? reject(new Error('No metadata found')) : resolve([codec, records])))
        decoder.on('error', reject)
    })
}

// Keys sorted by UTF-16 code units (the default JS sort), bytes as { $bytes: hex }.
function canonical(value) {
    if (Buffer.isBuffer(value)) {
        return { $bytes: value.toString('hex') }
    }
    if (Array.isArray(value)) {
        return value.map(canonical)
    }
    if (value !== null && typeof value === 'object') {
        const out = {}
        for (const key of Object.keys(value).sort()) {
            out[key] = canonical(value[key])
        }
        return out
    }
    return value
}

function zigzag(n) {
    const bytes = []
    let z = n >= 0 ? n * 2 : -n * 2 - 1
    while (z >= 0x80) {
        bytes.push((z % 0x80) | 0x80)
        z = Math.floor(z / 0x80)
    }
    bytes.push(z)
    return Buffer.from(bytes)
}

async function container(schema, blocks, { sync = Buffer.alloc(16, 7), badSyncAt = -1, rawData = false } = {}) {
    const schemaText = Buffer.from(JSON.stringify(schema))
    const header = Buffer.concat([
        Buffer.from('Obj\x01', 'latin1'),
        zigzag(2),
        zigzag(11), Buffer.from('avro.schema'), zigzag(schemaText.length), schemaText,
        zigzag(10), Buffer.from('avro.codec'), zigzag(9), Buffer.from('zstandard'),
        Buffer.from([0]),
        sync,
    ])
    const parts = [header]
    for (let i = 0; i < blocks.length; i++) {
        const [count, data] = blocks[i]
        const body = rawData ? data : await compress(data, 1)
        parts.push(zigzag(count), zigzag(body.length), body, i === badSyncAt ? Buffer.alloc(16, 9) : sync)
    }
    return Buffer.concat(parts)
}

async function edgeContainers() {
    const schema = {
        type: 'record',
        name: 'Edge',
        fields: [
            { name: 's', type: ['null', 'string'] },
            { name: 'l', type: ['null', 'long'] },
            { name: 'm', type: ['null', { type: 'map', values: 'string' }] },
            { name: 'a', type: { type: 'array', items: 'int' } },
            { name: 'b', type: 'boolean' },
            { name: 'd', type: 'double' },
            { name: 'f', type: 'float' },
            { name: 'e', type: { type: 'enum', name: 'E', symbols: ['A', 'B'] } },
            { name: 'x', type: { type: 'fixed', name: 'X', size: 2 } },
        ],
    }
    const type = avro.Type.forSchema(schema)
    const good = (i) =>
        type.toBuffer({ s: `row ${i}`, l: 1736942400000000 + i, m: { k: 'v', 1: 'one' }, a: [1, -2, 3], b: true, d: 0.1, f: 1.5, e: 'B', x: Buffer.from([1, 2]) })
    const goodBlock = Buffer.concat([good(0), good(1)])
    const edges = []
    edges.push(['valid', await container(schema, [[2, goodBlock], [1, good(2)]])])
    const valid = edges[0][1]
    edges.push(['truncated-last-block', valid.subarray(0, valid.length - 5)])
    edges.push(['truncated-in-header', valid.subarray(0, 30)])
    edges.push(['three-bytes', Buffer.from('Obj')])
    edges.push(['bad-sync-second-block', await container(schema, [[2, goodBlock], [1, good(2)]], { badSyncAt: 1 })])
    edges.push(['bad-zstd', await container(schema, [[1, Buffer.from('not zstd at all')]], { rawData: true })])
    edges.push(['count-past-data', await container(schema, [[3, goodBlock]])])
    edges.push(['count-below-data', await container(schema, [[1, goodBlock]])])
    edges.push(['zero-count-block', await container(schema, [[0, goodBlock], [1, good(3)]])])
    edges.push(['bad-union-index', await container(schema, [[1, Buffer.concat([zigzag(5), good(0)])]])])
    edges.push(['unsafe-long', await container(schema, [[1, Buffer.concat([zigzag(0), zigzag(1), zigzag(2 ** 60), good(0).subarray(12)])]])])
    edges.push(['bad-enum-index', await container({ type: 'record', name: 'R', fields: [{ name: 'e', type: { type: 'enum', name: 'E', symbols: ['A'] } }] }, [[1, zigzag(3)]])])
    edges.push(['invalid-utf8', await container({ type: 'record', name: 'U', fields: [{ name: 's', type: 'string' }] }, [[1, Buffer.concat([zigzag(6), Buffer.from([0x61, 0xff, 0xe2, 0x82, 0x62, 0xed])])]])])
    edges.push(['map-proto-and-dups', await container({ type: 'record', name: 'M', fields: [{ name: 'm', type: { type: 'map', values: 'string' } }] }, [[1, Buffer.concat([zigzag(-3), zigzag(99), ...[['__proto__', 'p'], ['dup', '1'], ['dup', '2']].flatMap(([k, v]) => [zigzag(k.length), Buffer.from(k), zigzag(v.length), Buffer.from(v)]), zigzag(1), zigzag(2), Buffer.from('10'), zigzag(1), Buffer.from('t'), zigzag(0)])]])])
    edges.push(['trailing-garbage', Buffer.concat([valid, Buffer.from([1, 2, 3])])])
    return edges
}

;(async () => {
    const out = {}
    for (const file of fs.readdirSync(scenarioDir).filter((f) => f.endsWith('.json')).sort()) {
        const fixture = JSON.parse(fs.readFileSync(path.join(scenarioDir, file), 'utf8'))
        out[file] = []
        for (const batch of fixture.scenario.batches) {
            for (const message of batch) {
                if (message.value_b64 === null) {
                    out[file].push(null)
                    continue
                }
                try {
                    const [codec, records] = await decode(Buffer.from(message.value_b64, 'base64'))
                    const text = JSON.stringify(records.map(canonical))
                    out[file].push({
                        codec,
                        count: records.length,
                        sha256: createHash('sha256').update(text).digest('hex'),
                    })
                } catch (e) {
                    out[file].push({ error: e.message })
                }
            }
        }
    }
    out['edges'] = []
    for (const [name, buffer] of await edgeContainers()) {
        let result
        try {
            const [codec, records] = await decode(buffer)
            result = {
                codec,
                count: records.length,
                sha256: createHash('sha256').update(JSON.stringify(records.map(canonical))).digest('hex'),
            }
        } catch (e) {
            result = { error: e.message }
        }
        out['edges'].push({ name, value_b64: buffer.toString('base64'), result })
    }
    fs.writeFileSync(outFile, JSON.stringify(out, null, 1) + '\n')
})()
