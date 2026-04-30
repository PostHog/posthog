/**
 * Synthetic git smart HTTP for read-only plugin distribution.
 *
 * Synthesizes a virtual git repo from a file tree (path → content).
 * Implements just enough of the git smart HTTP protocol for `git clone`.
 * No actual git repo on disk. No push support. No delta compression.
 */

import { createHash } from 'node:crypto'

import { zlibSync } from 'fflate'

const OBJ_COMMIT = 1
const OBJ_TREE = 2
const OBJ_BLOB = 3

interface GitObject {
    type: number
    data: Uint8Array
    sha: string
}

interface TreeEntry {
    mode: string
    name: string
    sha: string
}

interface DirNode {
    files: Map<string, string>
    dirs: Map<string, DirNode>
}

export interface FileTree {
    [path: string]: string
}

// --- Git object creation ---

function enc(s: string): Uint8Array {
    return new TextEncoder().encode(s)
}

function hexToBytes(hex: string): Uint8Array {
    const bytes = new Uint8Array(hex.length / 2)
    for (let i = 0; i < hex.length; i += 2) {
        bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16)
    }
    return bytes
}

function concat(arrays: Uint8Array[]): Uint8Array {
    let len = 0
    for (const a of arrays) len += a.length
    const result = new Uint8Array(len)
    let offset = 0
    for (const a of arrays) {
        result.set(a, offset)
        offset += a.length
    }
    return result
}

function u32be(buf: Uint8Array, offset: number, value: number): void {
    buf[offset] = (value >>> 24) & 0xff
    buf[offset + 1] = (value >>> 16) & 0xff
    buf[offset + 2] = (value >>> 8) & 0xff
    buf[offset + 3] = value & 0xff
}

function gitHash(type: string, data: Uint8Array): string {
    const header = enc(`${type} ${data.length}\0`)
    return createHash('sha1').update(header).update(data).digest('hex')
}

function createBlob(content: string): GitObject {
    const data = enc(content)
    return { type: OBJ_BLOB, data, sha: gitHash('blob', data) }
}

function createTree(entries: TreeEntry[]): GitObject {
    const sorted = [...entries].sort((a, b) => {
        const aKey = a.mode.startsWith('40') ? a.name + '/' : a.name
        const bKey = b.mode.startsWith('40') ? b.name + '/' : b.name
        return aKey < bKey ? -1 : aKey > bKey ? 1 : 0
    })

    const parts: Uint8Array[] = []
    for (const entry of sorted) {
        parts.push(enc(`${entry.mode} ${entry.name}\0`))
        parts.push(hexToBytes(entry.sha))
    }

    const data = concat(parts)
    return { type: OBJ_TREE, data, sha: gitHash('tree', data) }
}

function createCommit(treeSha: string, message: string): GitObject {
    const ts = '1700000000 +0000'
    const text = `tree ${treeSha}\nauthor PostHog <mcp@posthog.com> ${ts}\ncommitter PostHog <mcp@posthog.com> ${ts}\n\n${message}\n`
    const data = enc(text)
    return { type: OBJ_COMMIT, data, sha: gitHash('commit', data) }
}

// --- File tree → git objects ---

export function synthesizeRepo(files: FileTree): { objects: GitObject[]; headSha: string } {
    const objects: GitObject[] = []
    const blobShas = new Map<string, string>()

    for (const [path, content] of Object.entries(files)) {
        const blob = createBlob(content)
        objects.push(blob)
        blobShas.set(path, blob.sha)
    }

    const root: DirNode = { files: new Map(), dirs: new Map() }

    for (const path of Object.keys(files)) {
        const parts = path.split('/')
        const filename = parts.pop()!
        let node = root
        for (const dir of parts) {
            if (!node.dirs.has(dir)) {
                node.dirs.set(dir, { files: new Map(), dirs: new Map() })
            }
            node = node.dirs.get(dir)!
        }
        node.files.set(filename, blobShas.get(path)!)
    }

    function buildTree(node: DirNode): string {
        const entries: TreeEntry[] = []
        for (const [name, sha] of node.files) {
            entries.push({ mode: '100644', name, sha })
        }
        for (const [name, child] of node.dirs) {
            entries.push({ mode: '40000', name, sha: buildTree(child) })
        }
        const tree = createTree(entries)
        objects.push(tree)
        return tree.sha
    }

    const rootSha = buildTree(root)
    const commit = createCommit(rootSha, 'PostHog plugin')
    objects.push(commit)

    return { objects, headSha: commit.sha }
}

// --- Packfile ---

function encodeObjHeader(type: number, size: number): Uint8Array {
    const bytes: number[] = []
    let b = (type << 4) | (size & 0x0f)
    size >>= 4
    if (size > 0) b |= 0x80
    bytes.push(b)
    while (size > 0) {
        b = size & 0x7f
        size >>= 7
        if (size > 0) b |= 0x80
        bytes.push(b)
    }
    return new Uint8Array(bytes)
}

function buildPackfile(objects: GitObject[]): Uint8Array {
    const parts: Uint8Array[] = []

    const header = new Uint8Array(12)
    header.set(enc('PACK'))
    u32be(header, 4, 2)
    u32be(header, 8, objects.length)
    parts.push(header)

    for (const obj of objects) {
        parts.push(encodeObjHeader(obj.type, obj.data.length))
        parts.push(new Uint8Array(zlibSync(obj.data)))
    }

    const body = concat(parts)
    const checksum = createHash('sha1').update(body).digest()
    return concat([body, new Uint8Array(checksum)])
}

// --- Pkt-line encoding ---

function pktLine(data: string): string {
    const len = data.length + 4
    return len.toString(16).padStart(4, '0') + data
}

function sideBandChunks(band: number, data: Uint8Array): Uint8Array[] {
    const MAX_CHUNK = 65515 // 65520 - 4 (length) - 1 (band)
    const chunks: Uint8Array[] = []
    let offset = 0

    while (offset < data.length) {
        const slice = data.subarray(offset, offset + MAX_CHUNK)
        const len = slice.length + 5
        const line = new Uint8Array(len)
        line.set(enc(len.toString(16).padStart(4, '0')))
        line[4] = band
        line.set(slice, 5)
        chunks.push(line)
        offset += slice.length
    }

    return chunks
}

// --- HTTP handlers ---

export function handleInfoRefs(headSha: string): Response {
    const caps = 'side-band-64k shallow symref=HEAD:refs/heads/main'
    let body = ''
    body += pktLine('# service=git-upload-pack\n')
    body += '0000'
    body += pktLine(`${headSha} HEAD\0${caps}\n`)
    body += pktLine(`${headSha} refs/heads/main\n`)
    body += '0000'

    return new Response(body, {
        headers: {
            'Content-Type': 'application/x-git-upload-pack-advertisement',
            'Cache-Control': 'no-cache',
        },
    })
}

export async function handleUploadPack(request: Request, objects: GitObject[], headSha: string): Promise<Response> {
    const body = await request.text()
    const isShallow = body.includes('deepen')
    const isDone = body.includes('done')

    const parts: Uint8Array[] = []

    if (isShallow) {
        parts.push(enc(pktLine(`shallow ${headSha}\n`)))
        parts.push(enc('0000'))
    }

    if (isDone) {
        parts.push(enc(pktLine('NAK\n')))
        parts.push(...sideBandChunks(1, buildPackfile(objects)))
        parts.push(enc('0000'))
    }

    const responseBytes = concat(parts)
    return new Response(responseBytes as unknown as BodyInit, {
        headers: {
            'Content-Type': 'application/x-git-upload-pack-result',
            'Cache-Control': 'no-cache',
        },
    })
}

// --- Repo cache ---

export class GitRepoCache {
    private cache = new Map<string, { objects: GitObject[]; headSha: string; contentHash: string }>()

    getOrBuild(key: string, files: FileTree): { objects: GitObject[]; headSha: string; contentHash: string } {
        const contentHash = createHash('sha256').update(JSON.stringify(files)).digest('hex')

        const cached = this.cache.get(key)
        if (cached && cached.contentHash === contentHash) {
            return cached
        }

        const repo = synthesizeRepo(files)
        const entry = { ...repo, contentHash }
        this.cache.set(key, entry)
        return entry
    }

    invalidateAll(): void {
        this.cache.clear()
    }
}
