import { memo } from 'react'

import { IconCommit, IconGitBranch, IconGithub } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'
import { ToolActivity } from './ToolActivity'
import { getContentText, stripCodeFences } from './toolContentUtils'
import { ToolOutput } from './ToolOutput'
import type { ToolRendererProps } from './toolRegistry'

/**
 * Bespoke cards for the `posthog-code-tools` MCP server (the coding agent's git/repo tools). Without
 * these the calls fall through to the generic MCP card (`Call posthog – mcp__…__git_signed_commit
 * (MCP)` over raw JSON); here the result text is parsed into clickable GitHub Verified-commit links
 * and linked repo rows. Registered in `toolRegistry` under both the bare and the `mcp__<server>__`
 * qualified key, since the resolver yields either depending on the wire adapter.
 */
export const POSTHOG_CODE_TOOLS_SERVER = 'posthog-code-tools'
const QUALIFIED_PREFIX = `mcp__${POSTHOG_CODE_TOOLS_SERVER}__`

type SignedGitTool = 'git_signed_commit' | 'git_signed_merge' | 'git_signed_rewrite'

const SIGNED_GIT_LABELS: Record<SignedGitTool, string> = {
    git_signed_commit: 'Signed commits',
    git_signed_merge: 'Signed merge',
    git_signed_rewrite: 'Signed force-update',
}

const OWNER_REPO_RE = /^[\w.-]+\/[\w.-]+$/
// Each commit line of a signed-git result reads `- <sha> <url>`; capture the sha and the GitHub URL.
const SIGNED_COMMIT_LINE_RE = /^-\s+([0-9a-f]{7,40})\s+(\S+)/gm

interface SignedCommit {
    sha: string
    url: string
}

interface RepoRow {
    nameWithOwner: string
    description?: string
}

/** The bare tool name regardless of which wire adapter produced the frame (qualified or bare). */
function bareCodeToolName(message: ToolCallMessage): string {
    const candidate = message.resolvedKey || message.claudeToolName || message.rawToolName || ''
    return candidate.startsWith(QUALIFIED_PREFIX) ? candidate.slice(QUALIFIED_PREFIX.length) : candidate
}

/** A non-empty input string, or undefined — keeps optional subtitles out of the card when absent. */
function inputStr(value: unknown): string | undefined {
    return typeof value === 'string' && value.trim() ? value : undefined
}

function parseSignedCommits(output: string): SignedCommit[] {
    return Array.from(output.matchAll(SIGNED_COMMIT_LINE_RE), (m) => ({ sha: m[1], url: m[2] }))
}

function parseRepoRows(output: string): RepoRow[] {
    const rows: RepoRow[] = []
    for (const raw of output.split('\n')) {
        const line = raw.trim()
        if (!line) {
            continue
        }
        const sep = line.indexOf(': ')
        const name = sep > 0 ? line.slice(0, sep).trim() : line
        if (!OWNER_REPO_RE.test(name)) {
            continue
        }
        const description = sep > 0 ? line.slice(sep + 2).trim() : ''
        rows.push({ nameWithOwner: name, description: description || undefined })
    }
    return rows
}

function CommitList({ commits }: { commits: SignedCommit[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            {commits.map((commit) => (
                <Link key={commit.sha} to={commit.url} target="_blank" targetBlankIcon className="font-mono text-xs">
                    {commit.sha.slice(0, 7)}
                </Link>
            ))}
        </div>
    )
}

function RepoList({ rows }: { rows: RepoRow[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            {rows.map((row) => (
                <div key={row.nameWithOwner} className="flex items-baseline gap-2 min-w-0 text-xs">
                    <Link
                        to={`https://github.com/${row.nameWithOwner}`}
                        target="_blank"
                        targetBlankIcon
                        className="font-mono shrink-0"
                    >
                        {row.nameWithOwner}
                    </Link>
                    {row.description && <span className="text-muted truncate">{row.description}</span>}
                </div>
            ))}
        </div>
    )
}

function SignedGitRenderer({
    message,
    icon,
    turnComplete,
    turnCancelled,
    tool,
}: ToolRendererProps & { tool: SignedGitTool }): JSX.Element {
    const output = stripCodeFences(getContentText(message.content))
    const commits = parseSignedCommits(output)
    const count = commits.length
    const title = count > 0 ? `${SIGNED_GIT_LABELS[tool]} · ${pluralize(count, 'commit')}` : SIGNED_GIT_LABELS[tool]

    let subtitle: string | undefined
    if (tool === 'git_signed_commit') {
        subtitle = inputStr(message.rawInput.message) ?? inputStr(message.rawInput.branch)
    } else if (tool === 'git_signed_merge') {
        const base = inputStr(message.rawInput.base)
        const branch = inputStr(message.rawInput.branch)
        subtitle = base && branch ? `${base} → ${branch}` : (base ?? branch)
    } else {
        subtitle = inputStr(message.rawInput.branch)
    }

    // Everything beyond the two header lines goes in the collapsible body: the parsed commit links, or
    // the raw text for idempotent / warning / unparsed responses.
    return (
        <ToolActivity
            message={message}
            icon={icon ?? (tool === 'git_signed_commit' ? <IconCommit /> : <IconGitBranch />)}
            title={title}
            subtitle={subtitle ? <span className="font-mono">{subtitle}</span> : undefined}
            body={count > 0 ? <CommitList commits={commits} /> : output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}

function CloneRepoRenderer({ message, icon, turnComplete, turnCancelled }: ToolRendererProps): JSX.Element {
    const output = stripCodeFences(getContentText(message.content))
    const repo = inputStr(message.rawInput.repo)
    const branch = inputStr(message.rawInput.branch)
    const repoHref = repo && OWNER_REPO_RE.test(repo) ? `https://github.com/${repo}` : undefined
    const subtitle = repo ? (
        <span className="font-mono">
            {repoHref ? (
                <Link to={repoHref} target="_blank" targetBlankIcon>
                    {repo}
                </Link>
            ) : (
                repo
            )}
            {branch ? ` · ${branch}` : ''}
        </span>
    ) : undefined

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconGithub />}
            title="Clone repository"
            subtitle={subtitle}
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}

function ListReposRenderer({ message, icon, turnComplete, turnCancelled }: ToolRendererProps): JSX.Element {
    const output = stripCodeFences(getContentText(message.content))
    const rows = parseRepoRows(output)
    const filter = inputStr(message.rawInput.query) ?? inputStr(message.rawInput.owner)

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconGithub />}
            title={rows.length > 0 ? `List repositories · ${rows.length}` : 'List repositories'}
            subtitle={filter ? <span className="font-mono">{filter}</span> : undefined}
            body={rows.length > 0 ? <RepoList rows={rows} /> : output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}

/** Dispatches a `posthog-code-tools` call to its bespoke card, falling back to the generic MCP card. */
export const PostHogCodeToolRenderer = memo(function PostHogCodeToolRenderer(props: ToolRendererProps): JSX.Element {
    const tool = bareCodeToolName(props.message)
    switch (tool) {
        case 'git_signed_commit':
        case 'git_signed_merge':
        case 'git_signed_rewrite':
            return <SignedGitRenderer {...props} tool={tool} />
        case 'clone_repo':
            return <CloneRepoRenderer {...props} />
        case 'list_repos':
            return <ListReposRenderer {...props} />
        default:
            return <GenericMcpToolRenderer {...props} />
    }
})
