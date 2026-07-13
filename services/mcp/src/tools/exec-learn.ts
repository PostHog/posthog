import type { SkillCatalog } from '@/skills/skill-catalog'

export interface ExecLearnGuide {
    id: string
    title: string
    description: string
    content: string
}

export type ExecLearnGuideSummary = Omit<ExecLearnGuide, 'content'>

const SKILL_COMMANDS = [
    'learn skills',
    'learn -s <query>',
    'learn <skill> [path]',
    'learn <skill> <path> -s <query>',
    'learn <skill> <path> --lines <start>:<end>',
] as const

/** Combines small bundled guides with the lazily downloaded product skills. */
export class ExecLearnCatalog {
    private readonly guidesById: Map<string, ExecLearnGuide>

    constructor(
        guides: readonly ExecLearnGuide[],
        private readonly skills: SkillCatalog | undefined
    ) {
        this.guidesById = new Map()
        for (const guide of guides) {
            if (guide.id === 'skills' || guide.id.startsWith('-')) {
                throw new Error(`Reserved exec learn guide ID: "${guide.id}"`)
            }
            if (this.guidesById.has(guide.id)) {
                throw new Error(`Duplicate exec learn guide ID: "${guide.id}"`)
            }
            if (skills?.has(guide.id)) {
                // Published skills win so a future collision cannot break every exec command.
                continue
            }
            this.guidesById.set(guide.id, guide)
        }
    }

    execute(input: string): string {
        const rest = input.trim()
        if (!rest) {
            return JSON.stringify({
                guides: this.listGuides(),
                skills: {
                    available: this.skills !== undefined,
                    commands: SKILL_COMMANDS,
                },
            })
        }

        if (rest === 'skills') {
            const skills = this.requireSkills()
            return JSON.stringify({ count: skills.size, skills: skills.listNames() })
        }

        if (rest === '-s' || rest.startsWith('-s ')) {
            return this.requireSkills().search(rest.slice(2).trim())
        }

        const [name, ...args] = rest.split(/\s+/)
        const guide = this.guidesById.get(name!)
        if (guide) {
            if (args.length > 0) {
                throw new Error(`Guide "${name}" does not accept a path or flags.`)
            }
            return guide.content
        }

        const skills = this.requireSkills()
        if (args.length === 0) {
            return skills.read(name!)
        }

        const [path, flag, ...flagArgs] = args
        if (!flag) {
            return skills.read(name!, path)
        }
        if (flag === '-s') {
            return skills.searchFile(name!, path!, flagArgs.join(' '))
        }
        if (flag === '--lines' && flagArgs.length === 1) {
            const range = flagArgs[0]!.match(/^(\d+):(\d+)$/)
            if (!range) {
                throw new Error('Usage: learn <skill> <path> --lines <start>:<end>')
            }
            return skills.readLines(name!, path!, Number(range[1]), Number(range[2]))
        }
        throw new Error(
            'Usage: learn <skill> [path], learn <skill> <path> -s <query>, or learn <skill> <path> --lines <start>:<end>'
        )
    }

    private listGuides(): ExecLearnGuideSummary[] {
        return [...this.guidesById.values()].map(({ content: _content, ...summary }) => summary)
    }

    private requireSkills(): SkillCatalog {
        if (!this.skills) {
            throw new Error('Product skills are temporarily unavailable. Core exec commands are still available.')
        }
        return this.skills
    }
}
