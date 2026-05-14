import { actions, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

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

const SEED_PAGES: WorkspacePage[] = [
    {
        path: 'README',
        name: 'README',
        folder: '',
        body: `# Founder workspace

Welcome to your workspace — the artifacts produced as you move through Founder Mode all live here as plain markdown files. Edit anything, and link between pages using \`[[Page name]]\` syntax (Obsidian-style).

## Phases

- [[Lean canvas]] — the one-page snapshot of your idea
- [[Validation report]] — what we learned pressure-testing assumptions
- [[Landing page spec]] — the build brief for your first page
- [[GTM plan]] — where and how to launch
- [[MVP scope]] — what's in v1, what isn't
- [[Practical steps]] — concrete next actions this week

## How to use this

- Click any \`[[wiki link]]\` to jump to that page.
- Click a **red dashed link** to a missing page to create it.
- Edit the markdown on the left, see it rendered on the right.
- Folders organize pages by phase — Discovery, Validation, Launch.

> This is a mockup. Nothing persists across reloads yet.
`,
    },
    {
        path: 'Discovery/Lean canvas',
        name: 'Lean canvas',
        folder: 'Discovery',
        body: `# Lean canvas

A one-page snapshot of the idea, generated from your chat with the co-founder agent. Cross-reference: [[Idea notes]], [[Validation report]].

## Problem
Founders waste weeks shaping vague ideas into something testable. They jump to building before they know what they're building.

## Customer segments
Early-stage solo founders and small teams in the first 90 days of an idea.

## Unique value proposition
A guided cofounder that takes you from messy idea → validated brief → launch artifacts, end-to-end.

## Solution
Step-by-step chat that fills a lean canvas, runs a validation pass, drafts a landing page spec, and proposes a GTM plan.

## Channels
PostHog community, IndieHackers, founder-focused podcasts, X.

## Revenue streams
Bundled with PostHog seat — no separate SKU yet.

## Cost structure
LLM inference, light infra.

## Key metrics
Founders who reach a published landing page within 7 days.

## Unfair advantage
PostHog has the founder audience already — distribution.
`,
    },
    {
        path: 'Discovery/Idea notes',
        name: 'Idea notes',
        folder: 'Discovery',
        body: `# Idea notes

Loose thoughts that fed into the [[Lean canvas]].

- A lot of would-be founders get stuck before the first line of code.
- The cofounder loop should be **opinionated** — narrow questions, structured artifacts.
- Risk: this becomes another "AI brainstorm" toy. Mitigation: every step produces a real artifact you can ship.

Open questions:
- How much of the validation pass should be agentic vs. user-driven?
- Should artifacts live in PostHog or be exportable to Notion / Obsidian?
`,
    },
    {
        path: 'Validation/Validation report',
        name: 'Validation report',
        folder: 'Validation',
        body: `# Validation report

Output of the validation pass run against the [[Lean canvas]].

## Riskiest assumptions
1. **Founders will let a chat shape their idea.** Medium risk — many prefer to think alone.
2. **The artifacts produced are good enough to ship.** High risk — LLM-drafted landing pages are often generic.
3. **PostHog's existing audience overlaps with first-90-days founders.** Low risk — measurable from existing community.

## Evidence
- [[Interview notes]] — 5 founders, 30-min sessions.
- 4/5 said they'd use a "founder cofounder" if it produced real artifacts, not just summaries.
- 2/5 already use Obsidian for idea capture — strong signal for the workspace concept.

## Next
- Sharpen [[Landing page spec]] based on objections raised.
- Tighten [[MVP scope]] to focus on artifact quality.
`,
    },
    {
        path: 'Validation/Interview notes',
        name: 'Interview notes',
        folder: 'Validation',
        body: `# Interview notes

Raw notes from validation interviews. Synthesized into [[Validation report]].

## Founder A — fintech, pre-PMF
- Has 3 abandoned Notion docs about idea variants.
- "I'd pay for something that forces me to commit to one shape."
- Bounced on the word "co-founder" — felt overpromising.

## Founder B — dev tools
- Already running PostHog.
- Wants the GTM plan more than the canvas.
- "Don't give me a landing page draft — give me a list of 20 places to post."

## Founder C — consumer
- Skeptical of AI for ideation.
- Would use it for the **artifact pass** at the end, not for the idea-shaping step.
`,
    },
    {
        path: 'Launch/Landing page spec',
        name: 'Landing page spec',
        folder: 'Launch',
        body: `# Landing page spec

Build brief for the v1 landing page. Sourced from [[Lean canvas]] and refined by [[Validation report]].

## Hero
- **Headline:** "From idea to launch artifacts in one afternoon."
- **Subhead:** Founder Mode walks you through the lean canvas, validation, landing page, and GTM — and gives you the files at the end.
- **CTA:** Try the cofounder

## Sections
1. The 4 artifacts you walk away with
2. How the cofounder chat works (3-step explainer)
3. What other founders said ([[Interview notes]] excerpts)
4. Pricing — bundled with PostHog seat
5. Footer CTA + waitlist

## Out of scope for v1
- Video hero
- Live demo embed
- Comparison table

See [[GTM plan]] for where this lands first.
`,
    },
    {
        path: 'Launch/GTM plan',
        name: 'GTM plan',
        folder: 'Launch',
        body: `# GTM plan

How we get the first 100 founders onto [[Landing page spec]].

## Launch channels (ordered)
1. **PostHog community Slack** — soft launch, gather feedback.
2. **IndieHackers** — long-form post about the [[Validation report]] process.
3. **X** — thread from PostHog founder accounts.
4. **HackerNews "Show HN"** — once landing page polished.

## Messaging
- Lead with the artifacts, not the AI.
- Show the workspace screenshot — this page!
- Cross-link to [[MVP scope]] for what's actually shipped.

## Success metrics
- 100 signups in week 1
- 30 walk the full flow
- 10 produce a landing page they actually publish
`,
    },
    {
        path: 'Launch/MVP scope',
        name: 'MVP scope',
        folder: 'Launch',
        body: `# MVP scope

What's in v1. What's not. Constrains [[Landing page spec]] and [[GTM plan]].

## In
- Cofounder chat producing [[Lean canvas]]
- Validation pass producing [[Validation report]]
- Landing page spec generation
- GTM plan generation
- Workspace for viewing artifacts (you're in it)

## Not in v1
- Multi-project per user
- Exporting workspace to Obsidian / Notion
- Collaboration / sharing
- Real persistence of workspace edits (currently in-memory only)
- Programmatic publishing of the landing page

## Stretch
- Embed live PostHog analytics into the workspace for the launched page.
`,
    },
    {
        path: 'Launch/Practical steps',
        name: 'Practical steps',
        folder: 'Launch',
        body: `# Practical steps

Concrete actions this week. Pulled from [[GTM plan]] and [[MVP scope]].

- [ ] Polish workspace (this thing) — wiki links, sidebar, edit
- [ ] Finalize [[Landing page spec]] copy
- [ ] Draft the IndieHackers post
- [ ] Schedule 5 more validation calls — see [[Interview notes]] for what's worked
- [ ] Cut a 60-second screen recording of the cofounder flow
`,
    },
]

const seedPageMap = (): Record<string, WorkspacePage> => {
    const map: Record<string, WorkspacePage> = {}
    for (const page of SEED_PAGES) {
        map[page.path] = page
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

    reducers({
        pages: [
            seedPageMap(),
            {
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
])
