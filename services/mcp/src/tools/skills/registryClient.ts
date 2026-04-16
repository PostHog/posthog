/**
 * Fetches and caches the PostHog skills registry index.
 *
 * The index is published as a release asset alongside each agent-skills build
 * (see .github/workflows/ci-agent-skills.yml). It's a small JSON document
 * describing every published skill; we fetch it on demand and hold it in a
 * module-level cache with a short TTL so successive tool calls are fast.
 */

export const SKILLS_INDEX_URL =
    'https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills-index.json'

const CACHE_TTL_MS = 5 * 60 * 1000 // 5 minutes

export type SkillIndexEntry = {
    name: string
    description: string
    archive_url: string
    sha256: string
    source_path: string
}

export type SkillsIndex = {
    version: string
    generated_at: string
    skills: SkillIndexEntry[]
}

let cached: { at: number; value: SkillsIndex } | undefined

export async function fetchSkillsIndex(): Promise<SkillsIndex> {
    const now = Date.now()
    if (cached && now - cached.at < CACHE_TTL_MS) {
        return cached.value
    }

    // Use a standard Fetch; freshness is controlled by our in-process TTL above.
    const response = await fetch(SKILLS_INDEX_URL, { cache: 'no-store' })

    if (!response.ok) {
        throw new Error(`Failed to fetch skills index (${response.status}): ${await response.text()}`)
    }

    const value = (await response.json()) as SkillsIndex
    cached = { at: now, value }
    return value
}

export function findSkill(index: SkillsIndex, name: string): SkillIndexEntry | undefined {
    return index.skills.find((s) => s.name === name)
}
