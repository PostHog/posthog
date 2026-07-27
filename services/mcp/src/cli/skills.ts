import { unzipSync } from 'fflate'
import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive } from '@/resources/internals'
import type { ContextMillResource } from '@/resources/manifest-types'

import { errorCode } from './utils'

export interface SkillListItem {
    id: string
    name: string
    description: string
    tags: string[]
}

export interface SkillInstallResult {
    id: string
    directory: string
    fileCount: number
}

async function loadSkills(): Promise<{ archive: ReturnType<typeof unzipSync>; entries: ContextMillResource[] }> {
    const archive = await fetchContextMillResources(process.env.POSTHOG_MCP_LOCAL_SKILLS_URL)
    const manifest = loadManifestFromArchive(archive)
    return { archive, entries: filterValidEntries(manifest.resources, archive) }
}

export async function listSkills(): Promise<SkillListItem[]> {
    const { entries } = await loadSkills()
    return entries
        .map((entry) => ({
            id: entry.id,
            name: entry.name,
            description: typeof entry.description === 'string' ? entry.description : entry.resource.description,
            tags: Array.isArray(entry.tags) ? entry.tags.filter((tag): tag is string => typeof tag === 'string') : [],
        }))
        .sort((a, b) => a.id.localeCompare(b.id))
}

function targetSkillDirectory(targetRoot: string, skillId: string): string {
    assertSafeSkillId(skillId)
    const skillsRoot = path.resolve(targetRoot, '.agents', 'skills')
    const destinationRoot = path.resolve(skillsRoot, skillId)
    assertSafeDestination(skillsRoot, destinationRoot)
    return destinationRoot
}

function assertSafeDestination(root: string, destination: string): void {
    const normalizedRoot = path.resolve(root)
    const normalizedDestination = path.resolve(destination)
    if (normalizedDestination !== normalizedRoot && !normalizedDestination.startsWith(normalizedRoot + path.sep)) {
        throw new Error(`Refusing to write outside ${normalizedRoot}: ${normalizedDestination}`)
    }
}

function assertSafeSkillId(skillId: string): void {
    if (!skillId || skillId.includes('..') || /[/\\]/.test(skillId)) {
        throw new Error(`Invalid skill ID "${skillId}": must not contain path separators or traversal sequences.`)
    }
}

export async function installSkill(
    skillId: string,
    opts: { cwd?: string; force?: boolean } = {}
): Promise<SkillInstallResult> {
    const cwd = opts.cwd ?? process.cwd()
    const { archive, entries } = await loadSkills()
    const entry = entries.find((candidate) => candidate.id === skillId)
    if (!entry) {
        throw new Error(`Unknown skill "${skillId}". Run "posthog-cli api skill list" to see available skills.`)
    }
    if (!entry.file) {
        throw new Error(`Skill "${skillId}" has no downloadable archive.`)
    }

    const skillBytes = archive[entry.file]
    if (!skillBytes) {
        throw new Error(`Skill archive "${entry.file}" was not found.`)
    }

    const destinationRoot = targetSkillDirectory(cwd, skillId)
    try {
        await fs.access(destinationRoot)
        if (!opts.force) {
            throw new Error(`Skill "${skillId}" is already installed at ${destinationRoot}. Use --force to replace it.`)
        }
        await fs.rm(destinationRoot, { recursive: true, force: true })
    } catch (error) {
        if (errorCode(error) !== 'ENOENT') {
            throw error
        }
    }

    await fs.mkdir(destinationRoot, { recursive: true })
    const skillArchive = unzipSync(skillBytes)
    let fileCount = 0

    for (const [fileName, bytes] of Object.entries(skillArchive)) {
        if (fileName.endsWith('/')) {
            continue
        }
        const destination = path.resolve(destinationRoot, fileName)
        assertSafeDestination(destinationRoot, destination)
        await fs.mkdir(path.dirname(destination), { recursive: true })
        await fs.writeFile(destination, Buffer.from(bytes))
        fileCount += 1
    }

    return { id: skillId, directory: destinationRoot, fileCount }
}
