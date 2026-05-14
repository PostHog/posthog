import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import api from 'lib/api'

import { renderBuildSpecMarkdown } from '../components/buildSpecMarkdown'
import type { LandingPageBuildSpec } from '../components/founderLandingPageLogic'
import type { workspaceLogicType } from './workspaceLogicType'

export interface WorkspacePage {
    path: string
    name: string
    folder: string
    body: string
}

export interface WorkspaceFolder {
    name: string
    path: string
    children: WorkspaceFolder[]
    files: WorkspacePage[]
}

interface FounderProjectListItem {
    id: string
}

interface FounderProjectShape {
    id: string
    name: string
    ideation?: Record<string, unknown> | null
    validation?: Record<string, unknown> | null
    gtm?: Record<string, unknown> | null
    mvp?: Record<string, unknown> | null
    marketing_page?: Record<string, unknown> | null
    marketing_steps?: Record<string, unknown> | null
}

const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'

const buildReadme = (project: FounderProjectShape): string => {
    return `# ${project.name || 'Founder workspace'}

Everything Founder Mode produced for this idea, organized as plain markdown pages. Use \`[[Page name]]\` to link between pages.

## What's in here

- [[Idea]] — your starting point from the ideation chat
- [[Validation report]] — competitors, score, differentiation
- [[GTM plan]] — positioning, segments, channels, pricing
- [[MVP spec]] — one-liner, core flow, must-haves
- [[Landing page spec]] — full build brief: copy, brand, sections, events
- [[Marketing plan]] — launch playbook with ready-to-post content

## How to use this

- Click any \`[[wiki link]]\` to jump to that page.
- Edit the markdown on the left, see it rendered on the right.
- Pages are derived from your Founder Mode project — refresh the browser to pull the latest.
- Folders organize pages by stage.
`
}

const buildIdea = (project: FounderProjectShape): string => {
    const ideation = project.ideation as Record<string, string> | null | undefined
    if (!ideation || Object.keys(ideation).length === 0) {
        return `# Idea\n\n_Not completed yet. Go through the ideation chat to fill this in._`
    }
    const lines: string[] = ['# Idea', '']
    if (ideation.idea || ideation.problem) {
        lines.push(ideation.idea || ideation.problem, '')
    }
    if (ideation.what) {
        lines.push('## What', '', ideation.what, '')
    }
    if (ideation.how) {
        lines.push('## How', '', ideation.how, '')
    }
    if (ideation.who) {
        lines.push('## Who', '', ideation.who, '')
    }
    if (ideation.problem && ideation.idea && ideation.problem !== ideation.idea) {
        lines.push('## Problem', '', ideation.problem, '')
    }
    return lines.join('\n').trim() + '\n'
}

const buildValidation = (project: FounderProjectShape): string => {
    const validation = project.validation as Record<string, unknown> | null | undefined
    const report = validation?.report as Record<string, unknown> | null | undefined
    if (!report) {
        return `# Validation report\n\n_Not completed yet. Run the validation pass to fill this in._`
    }
    const lines: string[] = ['# Validation report', '']
    const verdict = report.verdict as Record<string, unknown> | null
    if (verdict) {
        lines.push(`**Score:** ${verdict.score}/10  ·  **Confidence:** ${verdict.confidence}`, '')
        if (verdict.rationale) {
            lines.push(String(verdict.rationale), '')
        }
    }
    const competitors = report.competitors as Array<Record<string, string>> | null
    if (competitors?.length) {
        lines.push('## Competitors', '')
        for (const c of competitors) {
            lines.push(`- **${c.name}** — ${c.positioning || c.description || '(no positioning)'}`)
        }
        lines.push('')
        lines.push('See also: [[Competitors]] for the full profiles.')
        lines.push('')
    }
    const diff = report.differentiation as Record<string, string> | null
    if (diff) {
        lines.push('## Differentiation', '')
        if (diff.summary) {
            lines.push(diff.summary, '')
        }
        if (diff.moat) {
            lines.push(`**Moat:** ${diff.moat}`, '')
        }
    }
    return lines.join('\n').trim() + '\n'
}

const buildCompetitors = (project: FounderProjectShape): string => {
    const report = (project.validation as Record<string, unknown> | null | undefined)?.report as
        | Record<string, unknown>
        | null
        | undefined
    const competitors = report?.competitors as Array<Record<string, string>> | null
    if (!competitors?.length) {
        return ''
    }
    const lines: string[] = ['# Competitors', '', 'Profiles of the alternatives users would compare against.', '']
    for (const c of competitors) {
        lines.push(`## ${c.name}`, '')
        if (c.positioning) {
            lines.push(`**Positioning:** ${c.positioning}`, '')
        }
        if (c.description) {
            lines.push(c.description, '')
        }
        if (c.url) {
            lines.push(`[${c.url}](${c.url})`, '')
        }
    }
    return lines.join('\n').trim() + '\n'
}

const buildGTM = (project: FounderProjectShape): string => {
    const gtm = project.gtm as Record<string, unknown> | null | undefined
    const result = gtm?.result as Record<string, unknown> | null | undefined
    if (!result) {
        return `# GTM plan\n\n_Not completed yet. Run the GTM stage to fill this in._`
    }
    const lines: string[] = ['# GTM plan', '']
    if (result.positioning_statement) {
        lines.push('## Positioning', '', String(result.positioning_statement), '')
    }
    const segment = result.primary_segment as Record<string, string> | null
    if (segment) {
        lines.push('## Primary segment', '', `**${segment.name}** — ${segment.description}`, '')
    }
    if (result.moat) {
        lines.push('## Moat', '', String(result.moat), '')
    }
    if (result.pricing_philosophy) {
        lines.push('## Pricing', '', String(result.pricing_philosophy), '')
    }
    const channels = [result.primary_channel as string, ...((result.secondary_channels as string[]) || [])].filter(
        Boolean
    )
    if (channels.length) {
        lines.push('## Channels', '')
        for (const c of channels) {
            lines.push(`- ${c}`)
        }
        lines.push('')
    }
    return lines.join('\n').trim() + '\n'
}

const buildMVP = (project: FounderProjectShape): string => {
    const mvp = project.mvp as Record<string, unknown> | null | undefined
    const result = mvp?.result as Record<string, unknown> | null | undefined
    if (!result) {
        return `# MVP spec\n\n_Not completed yet. Run the MVP stage to fill this in._`
    }
    const lines: string[] = ['# MVP spec', '']
    if (result.one_liner) {
        lines.push(String(result.one_liner), '')
    }
    const flow = result.core_flow as Array<Record<string, string | number>> | null
    if (flow?.length) {
        lines.push('## Core flow', '')
        for (const s of flow) {
            lines.push(`${s.step}. **${s.user_action}** → ${s.system_response}  _(✓ ${s.success_signal})_`)
        }
        lines.push('')
    }
    const mustHaves = result.must_haves as string[] | null
    if (mustHaves?.length) {
        lines.push('## Must-haves', '')
        for (const m of mustHaves) {
            lines.push(`- ${m}`)
        }
        lines.push('')
    }
    const excluded = result.deliberately_excluded as string[] | null
    if (excluded?.length) {
        lines.push('## Deliberately excluded', '')
        for (const e of excluded) {
            lines.push(`- ${e}`)
        }
        lines.push('')
    }
    return lines.join('\n').trim() + '\n'
}

const buildLandingPageSpec = (project: FounderProjectShape): string => {
    const mp = project.marketing_page as Record<string, unknown> | null | undefined
    const spec = (mp?.page ?? mp?.result) as LandingPageBuildSpec | null | undefined
    if (!spec) {
        return `# Landing page spec\n\n_Not completed yet. Generate the landing page build spec to fill this in._`
    }
    try {
        return renderBuildSpecMarkdown(spec)
    } catch {
        return `# Landing page spec\n\n_Build spec data could not be rendered._`
    }
}

const PLATFORM_LABELS: Record<string, string> = {
    product_hunt: 'Product Hunt',
    producthunt: 'Product Hunt',
    linkedin: 'LinkedIn',
    twitter: 'Twitter / X',
    'twitter/x': 'Twitter / X',
    reddit: 'Reddit',
    hacker_news: 'Hacker News',
    hackernews: 'Hacker News',
    indie_hackers: 'Indie Hackers',
}

const platformLabel = (raw: string): string => PLATFORM_LABELS[raw.toLowerCase()] ?? raw

const buildMarketing = (project: FounderProjectShape): string => {
    const ms = project.marketing_steps as Record<string, unknown> | null | undefined
    const result = ms?.result as Record<string, unknown> | null | undefined
    if (!result) {
        return `# Marketing plan\n\n_Not completed yet. Generate the marketing plan to fill this in._`
    }
    const lines: string[] = ['# Marketing plan', '']
    if (result.launch_summary) {
        lines.push(String(result.launch_summary), '')
    }
    const communities = result.target_communities as string[] | null
    if (communities?.length) {
        lines.push('## Where to post', '')
        for (const c of communities) {
            lines.push(`- ${c}`)
        }
        lines.push('')
    }
    const steps = result.steps as Array<Record<string, unknown>> | null
    if (steps?.length) {
        lines.push('## Launch steps', '')
        for (const step of steps) {
            lines.push(`### ${step.title}  ·  _${step.channel} · ${step.timeline}_`, '')
            if (step.description) {
                lines.push(String(step.description), '')
            }
            const posts = step.ready_to_use_content as Array<Record<string, string>> | null
            if (posts?.length) {
                for (const post of posts) {
                    lines.push(`#### ${platformLabel(post.platform)}`, '')
                    lines.push('```')
                    lines.push(post.content)
                    lines.push('```', '')
                    if (post.tips) {
                        lines.push(`> 💡 ${post.tips}`, '')
                    }
                }
            }
        }
    }
    return lines.join('\n').trim() + '\n'
}

const pageAt = (path: string, name: string, folder: string, body: string): WorkspacePage => ({
    path,
    name,
    folder,
    body: body.trim() + '\n',
})

export const buildProjectPages = (project: FounderProjectShape | null): Record<string, WorkspacePage> => {
    if (!project) {
        return {}
    }
    const pages: WorkspacePage[] = [
        pageAt('README', 'README', '', buildReadme(project)),
        pageAt('Discovery/Idea', 'Idea', 'Discovery', buildIdea(project)),
        pageAt('Validation/Validation report', 'Validation report', 'Validation', buildValidation(project)),
    ]

    const competitorsMd = buildCompetitors(project)
    if (competitorsMd) {
        pages.push(pageAt('Validation/Competitors', 'Competitors', 'Validation', competitorsMd))
    }

    pages.push(
        pageAt('GTM/GTM plan', 'GTM plan', 'GTM', buildGTM(project)),
        pageAt('MVP/MVP spec', 'MVP spec', 'MVP', buildMVP(project)),
        pageAt('Launch/Landing page spec', 'Landing page spec', 'Launch', buildLandingPageSpec(project)),
        pageAt('Launch/Marketing plan', 'Marketing plan', 'Launch', buildMarketing(project))
    )

    const map: Record<string, WorkspacePage> = {}
    for (const p of pages) {
        map[p.path] = p
    }
    return map
}

export const buildTree = (pages: Record<string, WorkspacePage>): WorkspaceFolder => {
    const root: WorkspaceFolder = { name: '', path: '', children: [], files: [] }
    const folderMap: Record<string, WorkspaceFolder> = { '': root }

    const ensureFolder = (folderPath: string): WorkspaceFolder => {
        if (folderMap[folderPath]) {
            return folderMap[folderPath]
        }
        const segments = folderPath.split('/')
        const name = segments[segments.length - 1]
        const parentPath = segments.slice(0, -1).join('/')
        const parent = ensureFolder(parentPath)
        const folder: WorkspaceFolder = { name, path: folderPath, children: [], files: [] }
        parent.children.push(folder)
        folderMap[folderPath] = folder
        return folder
    }

    for (const page of Object.values(pages)) {
        const folder = ensureFolder(page.folder)
        folder.files.push(page)
    }

    const sortFolder = (folder: WorkspaceFolder): void => {
        folder.children.sort((a, b) => a.name.localeCompare(b.name))
        folder.files.sort((a, b) => a.name.localeCompare(b.name))
        folder.children.forEach(sortFolder)
    }
    sortFolder(root)
    return root
}

export const workspaceLogic = kea<workspaceLogicType>([
    path(['products', 'founder_mode', 'frontend', 'workspace', 'workspaceLogic']),

    actions({
        openPage: (pagePath: string) => ({ pagePath }),
        updateBody: (pagePath: string, body: string) => ({ pagePath, body }),
        createPage: (name: string, folder: string = '') => ({ name, folder }),
        deletePage: (pagePath: string) => ({ pagePath }),
        renamePage: (pagePath: string, newName: string) => ({ pagePath, newName }),
    }),

    loaders(() => ({
        project: [
            null as FounderProjectShape | null,
            {
                loadProject: async () => {
                    const list = await api.get<{ results: FounderProjectListItem[] }>(FOUNDER_PROJECTS_URL)
                    const first = list.results?.[0]
                    if (!first) {
                        return null
                    }
                    return await api.get<FounderProjectShape>(`${FOUNDER_PROJECTS_URL}${first.id}/`)
                },
            },
        ],
    })),

    reducers({
        pages: [
            {} as Record<string, WorkspacePage>,
            {
                loadProjectSuccess: (_, { project }) => buildProjectPages(project),
                updateBody: (state, { pagePath, body }) => {
                    if (!state[pagePath]) {
                        return state
                    }
                    return { ...state, [pagePath]: { ...state[pagePath], body } }
                },
                createPage: (state, { name, folder }) => {
                    const fullPath = folder ? `${folder}/${name}` : name
                    if (state[fullPath]) {
                        return state
                    }
                    return {
                        ...state,
                        [fullPath]: {
                            path: fullPath,
                            name,
                            folder,
                            body: `# ${name}\n\n`,
                        },
                    }
                },
                deletePage: (state, { pagePath }) => {
                    if (!state[pagePath]) {
                        return state
                    }
                    const { [pagePath]: _removed, ...rest } = state
                    return rest
                },
                renamePage: (state, { pagePath, newName }) => {
                    const existing = state[pagePath]
                    if (!existing) {
                        return state
                    }
                    const newPath = existing.folder ? `${existing.folder}/${newName}` : newName
                    if (state[newPath]) {
                        return state
                    }
                    const { [pagePath]: _removed, ...rest } = state
                    return {
                        ...rest,
                        [newPath]: { ...existing, name: newName, path: newPath },
                    }
                },
            },
        ],
        currentPath: [
            'README' as string,
            {
                openPage: (_, { pagePath }) => pagePath,
                createPage: (_, { name, folder }) => (folder ? `${folder}/${name}` : name),
                renamePage: (current, { pagePath, newName }) => {
                    if (current !== pagePath) {
                        return current
                    }
                    const segments = pagePath.split('/')
                    segments[segments.length - 1] = newName
                    return segments.join('/')
                },
                deletePage: (current, { pagePath }) => (current === pagePath ? 'README' : current),
            },
        ],
    }),

    selectors({
        tree: [(s) => [s.pages], (pages) => buildTree(pages)],
        currentPage: [
            (s) => [s.pages, s.currentPath],
            (pages, currentPath): WorkspacePage | null => pages[currentPath] ?? null,
        ],
        pagesByName: [
            (s) => [s.pages],
            (pages): Record<string, WorkspacePage> => {
                const map: Record<string, WorkspacePage> = {}
                for (const page of Object.values(pages)) {
                    map[page.name.toLowerCase()] = page
                }
                return map
            },
        ],
        hasProject: [(s) => [s.project, s.projectLoading], (project, loading) => !!project || loading],
    }),

    actionToUrl(({ values }) => ({
        openPage: () => ['/founder/workspace', { p: values.currentPath }],
        createPage: () => ['/founder/workspace', { p: values.currentPath }],
        renamePage: () => ['/founder/workspace', { p: values.currentPath }],
        deletePage: () => ['/founder/workspace', { p: values.currentPath }],
    })),

    urlToAction(({ actions, values }) => ({
        '/founder/workspace': (_: unknown, searchParams: Record<string, string>) => {
            const p = searchParams.p
            if (p && p !== values.currentPath && values.pages[p]) {
                actions.openPage(p)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadProject()
    }),
])
