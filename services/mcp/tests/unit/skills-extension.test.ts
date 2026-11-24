import { strToU8, zipSync } from 'fflate'
import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'

import { getSkill, listSkills, readSkillFile, UnknownSkillResourceError } from '@/hono/skills-extension'
import { SkillCatalog } from '@/skills/skill-catalog'

function makeCatalog(files: Record<string, string>): SkillCatalog {
    return SkillCatalog.fromZip(
        zipSync(Object.fromEntries(Object.entries(files).map(([path, content]) => [path, strToU8(content)])))
    )
}

function skillMd(name: string, extraFrontmatter = ''): string {
    return `---\nname: ${name}\ndescription: Describes ${name}. 日本語\n${extraFrontmatter}---\n\n# ${name}\n`
}

describe('skills extension', () => {
    it('lists every frontmatter field and a manifest that matches the bytes resources/read serves', () => {
        const catalog = makeCatalog({
            'funnels/SKILL.md': skillMd('funnels', 'metadata:\n  owner: growth\n'),
            'funnels/references/my guide.md': '# Guide\r\n\r\nUse a funnel.\n',
            'funnels/scripts/run.ts': 'export {}\n',
        })

        const { skills, nextCursor } = listSkills(catalog)

        expect(nextCursor).toBeUndefined()
        expect(skills).toHaveLength(1)
        expect(skills[0]!.uri).toBe('skill://funnels/SKILL.md')
        expect(skills[0]!.frontmatter).toEqual({
            name: 'funnels',
            description: 'Describes funnels. 日本語',
            metadata: { owner: 'growth' },
        })
        expect(skills[0]!.resources.map((resource) => resource.uri)).toEqual([
            'skill://funnels/SKILL.md',
            'skill://funnels/references/my%20guide.md',
            'skill://funnels/scripts/run.ts',
        ])
        for (const resource of skills[0]!.resources) {
            const [content] = readSkillFile(catalog, resource.uri).contents
            const bytes = Buffer.from((content as { text: string }).text, 'utf8')
            expect(resource.size).toBe(bytes.byteLength)
            expect(resource.digest).toBe(`sha256:${createHash('sha256').update(bytes).digest('hex')}`)
        }
        expect(getSkill(catalog, 'skill://funnels/SKILL.md').skill).toEqual(skills[0])
    })

    it('pages through every skill exactly once', () => {
        const names = Array.from({ length: 120 }, (_, index) => `skill-${String(index).padStart(3, '0')}`)
        const catalog = makeCatalog(Object.fromEntries(names.map((name) => [`${name}/SKILL.md`, skillMd(name)])))

        const seen: string[] = []
        let cursor: string | undefined
        do {
            const page = listSkills(catalog, cursor)
            seen.push(...page.skills.map((skill) => skill.frontmatter.name as string))
            cursor = page.nextCursor
        } while (cursor)

        expect(seen).toEqual(names)
    })

    it.each([
        ['an unknown skill', 'skill://missing/SKILL.md'],
        ['a supporting file, which is not a skill', 'skill://funnels/references/guide.md'],
    ])('rejects skills/get for %s', (_case, uri) => {
        const catalog = makeCatalog({
            'funnels/SKILL.md': skillMd('funnels'),
            'funnels/references/guide.md': '# Guide\n',
        })

        expect(() => getSkill(catalog, uri)).toThrow(UnknownSkillResourceError)
    })

    it('serves nothing when no catalog is available', () => {
        expect(listSkills(undefined)).toEqual({ skills: [] })
        expect(() => getSkill(undefined, 'skill://funnels/SKILL.md')).toThrow(UnknownSkillResourceError)
        expect(() => readSkillFile(undefined, 'skill://funnels/SKILL.md')).toThrow(UnknownSkillResourceError)
    })
})
