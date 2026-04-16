import type { z } from 'zod'

import { SkillsGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { fetchSkillsIndex, findSkill, type SkillIndexEntry } from './registryClient'

const schema = SkillsGetSchema

type Params = z.infer<typeof schema>

type SkillFilePayload = {
    path: string
    content: string
}

type Result = {
    metadata: SkillIndexEntry
    files: SkillFilePayload[]
}

const MAX_SKILL_BYTES = 2 * 1024 * 1024 // 2 MiB — skills are markdown; anything larger is a red flag.

async function downloadSkillFiles(entry: SkillIndexEntry): Promise<SkillFilePayload[]> {
    const response = await fetch(entry.archive_url)
    if (!response.ok) {
        throw new Error(
            `Failed to fetch skill archive for '${entry.name}' (${response.status}): ${await response.text()}`
        )
    }

    const buf = await response.arrayBuffer()
    if (buf.byteLength > MAX_SKILL_BYTES) {
        throw new Error(
            `Skill '${entry.name}' archive is ${buf.byteLength} bytes, exceeding the ${MAX_SKILL_BYTES} byte limit.`
        )
    }

    const files = await extractZipTextFiles(new Uint8Array(buf))
    return files
}

/**
 * Minimal pure-TS zip reader for text files — avoids pulling a zip library
 * into the Worker bundle. Supports stored (method 0) and deflated (method 8)
 * entries, which are the only ones produced by Python's zipfile in this repo.
 */
async function extractZipTextFiles(data: Uint8Array): Promise<SkillFilePayload[]> {
    // Locate End of Central Directory record by scanning from the tail.
    const EOCD_SIG = 0x06054b50
    const CD_SIG = 0x02014b50
    const LF_SIG = 0x04034b50

    const view = new DataView(data.buffer, data.byteOffset, data.byteLength)

    let eocdOffset = -1
    for (let i = data.length - 22; i >= Math.max(0, data.length - 65557); i--) {
        if (view.getUint32(i, true) === EOCD_SIG) {
            eocdOffset = i
            break
        }
    }
    if (eocdOffset < 0) {
        throw new Error('Invalid zip archive: EOCD not found')
    }

    const totalEntries = view.getUint16(eocdOffset + 10, true)
    const cdOffset = view.getUint32(eocdOffset + 16, true)

    const files: SkillFilePayload[] = []
    let cursor = cdOffset
    const decoder = new TextDecoder('utf-8', { fatal: false })

    for (let i = 0; i < totalEntries; i++) {
        if (view.getUint32(cursor, true) !== CD_SIG) {
            throw new Error(`Invalid zip archive: bad CD signature at ${cursor}`)
        }
        const method = view.getUint16(cursor + 10, true)
        const compressedSize = view.getUint32(cursor + 20, true)
        const nameLen = view.getUint16(cursor + 28, true)
        const extraLen = view.getUint16(cursor + 30, true)
        const commentLen = view.getUint16(cursor + 32, true)
        const localHeaderOffset = view.getUint32(cursor + 42, true)
        const name = decoder.decode(data.slice(cursor + 46, cursor + 46 + nameLen))
        cursor += 46 + nameLen + extraLen + commentLen

        // Directories end with '/'.
        if (name.endsWith('/')) {
            continue
        }

        if (view.getUint32(localHeaderOffset, true) !== LF_SIG) {
            throw new Error(`Invalid zip archive: bad local header for '${name}'`)
        }
        const lhNameLen = view.getUint16(localHeaderOffset + 26, true)
        const lhExtraLen = view.getUint16(localHeaderOffset + 28, true)
        const dataStart = localHeaderOffset + 30 + lhNameLen + lhExtraLen
        const dataEnd = dataStart + compressedSize

        let contentBytes: Uint8Array
        if (method === 0) {
            contentBytes = data.slice(dataStart, dataEnd)
        } else if (method === 8) {
            const ds = new DecompressionStream('deflate-raw')
            const writable = ds.writable.getWriter()
            await writable.write(data.slice(dataStart, dataEnd))
            await writable.close()
            contentBytes = new Uint8Array(await new Response(ds.readable).arrayBuffer())
        } else {
            throw new Error(`Unsupported zip compression method ${method} for '${name}'`)
        }

        files.push({ path: name, content: decoder.decode(contentBytes) })
    }

    // Keep SKILL.md first for easy consumption by agents that only read the entry point.
    files.sort((a, b) => {
        if (a.path === 'SKILL.md') {
            return -1
        }
        if (b.path === 'SKILL.md') {
            return 1
        }
        return a.path.localeCompare(b.path)
    })

    return files
}

export const skillsGetHandler: ToolBase<typeof schema, Result>['handler'] = async (
    _context: Context,
    params: Params
) => {
    const index = await fetchSkillsIndex()
    const entry = findSkill(index, params.name)
    if (!entry) {
        throw new Error(`Skill '${params.name}' not found. Call skills-list to discover available skills.`)
    }

    const files = await downloadSkillFiles(entry)
    return { metadata: entry, files }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'skills-get',
    schema,
    handler: skillsGetHandler,
})

export default tool
