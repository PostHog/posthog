import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive } from '@/resources/internals'
import type { ContextMillResource } from '@/resources/manifest-types'
import { unzipUntrusted } from '@/skills/skill-catalog'

import { assertResolvesInside, assertSafeDestination, errorCode } from './utils'

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

export interface InstallableSkills {
    entries: ContextMillResource[]
    readFile(name: string): Uint8Array | undefined
}

export class SkillInstallError extends Error {
    constructor(
        readonly code: 'unknown_skill' | 'invalid_skill_id' | 'already_installed',
        message: string
    ) {
        super(message)
        this.name = 'SkillInstallError'
    }
}

async function loadSkills(): Promise<InstallableSkills> {
    const archive = await fetchContextMillResources(process.env.POSTHOG_MCP_LOCAL_SKILLS_URL)
    const manifest = loadManifestFromArchive(archive)

    return { entries: filterValidEntries(manifest.resources, archive), readFile: (name) => archive[name] }
}

export async function listSkills(source?: InstallableSkills): Promise<SkillListItem[]> {
    const { entries } = source ?? (await loadSkills())
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

function assertSafeSkillId(skillId: string): void {
    if (!skillId || skillId.includes('..') || /[/\\]/.test(skillId)) {
        throw new SkillInstallError(
            'invalid_skill_id',
            `Invalid skill ID "${skillId}": must not contain path separators or traversal sequences.`
        )
    }
}

export async function installSkill(
    skillId: string,
    opts: { cwd?: string; force?: boolean; source?: InstallableSkills } = {}
): Promise<SkillInstallResult> {
    const cwd = opts.cwd ?? process.cwd()
    const source = opts.source ?? (await loadSkills())
    const entry = source.entries.find((candidate) => candidate.id === skillId)

    if (!entry) {
        throw new SkillInstallError(
            'unknown_skill',
            `Unknown skill "${skillId}". Run "posthog-cli api skill list" to see available skills.`
        )
    }

    if (!entry.file) {
        throw new Error(`Skill "${skillId}" has no downloadable archive.`)
    }

    const skillBytes = source.readFile(entry.file)
    if (!skillBytes) {
        throw new Error(`Skill archive "${entry.file}" was not found.`)
    }

    // Unzipped before anything on disk changes, so an archive past the limits, or with an unsafe path, leaves an
    // installed copy as it is.
    const skillArchive = unzipUntrusted(skillBytes, `Skill archive "${entry.file}"`)
    const destinationRoot = targetSkillDirectory(cwd, skillId)
    await assertResolvesInside(cwd, destinationRoot)
    try {
        await fs.access(destinationRoot)
        if (!opts.force) {
            throw new SkillInstallError(
                'already_installed',
                `Skill "${skillId}" is already installed at ${destinationRoot}. Use --force to replace it.`
            )
        }
        await fs.rm(destinationRoot, { recursive: true, force: true })
    } catch (error) {
        if (errorCode(error) !== 'ENOENT') {
            throw error
        }
    }

    await fs.mkdir(destinationRoot, { recursive: true })
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
