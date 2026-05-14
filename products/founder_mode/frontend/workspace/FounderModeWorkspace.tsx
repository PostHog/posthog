import { useActions, useValues } from 'kea'
import * as React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { WorkspaceFolder, WorkspacePage, workspaceLogic } from './workspaceLogic'

const WIKI_RE = /\[\[([^\]]+)\]\]/g

export function FounderModeWorkspace(): JSX.Element {
    const { projectLoading, project } = useValues(workspaceLogic)

    if (projectLoading && !project) {
        return (
            <div className="flex items-center justify-center w-full h-[calc(100vh-3rem)] text-text-secondary">
                Loading your Founder Mode workspace…
            </div>
        )
    }

    if (!project) {
        return <EmptyState />
    }

    return (
        <div className="flex h-[calc(100vh-3rem)] w-full bg-bg-light text-text-primary">
            <Sidebar />
            <EditorPane />
        </div>
    )
}

function EmptyState(): JSX.Element {
    const { loadProject } = useActions(workspaceLogic)
    const [seeding, setSeeding] = React.useState(false)
    const [error, setError] = React.useState<string | null>(null)

    const handleSeed = async (): Promise<void> => {
        if (seeding) {
            return
        }
        setSeeding(true)
        setError(null)
        try {
            await api.create('api/projects/@current/founder_projects/seed_demo/', {})
            loadProject()
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e)
            setError(msg.includes('403') ? 'seed_demo is only available when DEBUG=true.' : msg)
        } finally {
            setSeeding(false)
        }
    }

    return (
        <div className="flex flex-col items-center justify-center w-full h-[calc(100vh-3rem)] gap-3 px-6 text-center">
            <h2 className="text-lg font-semibold">No founder project yet</h2>
            <p className="text-sm text-text-secondary max-w-md">
                The workspace renders everything Founder Mode produces — ideation, validation, GTM, MVP, landing page
                spec, and marketing plan. Start the flow first, or seed a demo project to see it all immediately.
            </p>
            <div className="flex items-center gap-3 mt-2">
                <Link to="/founder" className="text-sm font-medium">
                    Start in Founder Mode →
                </Link>
                <LemonButton type="secondary" onClick={handleSeed} loading={seeding}>
                    Seed demo data
                </LemonButton>
            </div>
            {error && <p className="text-xs text-danger mt-2 max-w-md">{error}</p>}
            <p className="text-[11px] text-text-tertiary mt-1">
                Seed wipes any existing project for this team and creates one with all 5 stages pre-populated.
            </p>
        </div>
    )
}

function Sidebar(): JSX.Element {
    const { tree, currentPath } = useValues(workspaceLogic)
    const { createPage } = useActions(workspaceLogic)

    const handleNew = (folder: string): void => {
        const name = window.prompt(folder ? `New page in "${folder}":` : 'New page name:')
        if (!name) {
            return
        }
        createPage(name.trim(), folder)
    }

    return (
        <aside className="w-72 shrink-0 border-r border-border bg-bg-3000 flex flex-col">
            <header className="px-4 py-3 border-b border-border flex items-center justify-between">
                <div>
                    <div className="text-xs uppercase tracking-wide text-text-secondary">Founder mode</div>
                    <div className="text-sm font-semibold">Workspace</div>
                </div>
                <button
                    type="button"
                    onClick={() => handleNew('')}
                    className="text-xs px-2 py-1 rounded border border-border hover:bg-fill-highlight-100 cursor-pointer"
                    title="New page at root"
                >
                    + New
                </button>
            </header>
            <nav className="flex-1 overflow-y-auto py-2 px-2 text-sm">
                <TreeNode folder={tree} currentPath={currentPath} onNewInFolder={handleNew} depth={0} />
            </nav>
            <footer className="px-4 py-2 border-t border-border text-[11px] text-text-secondary">
                Mockup — edits don't persist.
            </footer>
        </aside>
    )
}

function TreeNode({
    folder,
    currentPath,
    onNewInFolder,
    depth,
}: {
    folder: WorkspaceFolder
    currentPath: string
    onNewInFolder: (folder: string) => void
    depth: number
}): JSX.Element {
    return (
        <div>
            {folder.files.map((file) => (
                <FileRow key={file.path} file={file} isActive={file.path === currentPath} depth={depth} />
            ))}
            {folder.children.map((child) => (
                <FolderRow
                    key={child.path}
                    folder={child}
                    currentPath={currentPath}
                    onNewInFolder={onNewInFolder}
                    depth={depth}
                />
            ))}
        </div>
    )
}

function FileRow({ file, isActive, depth }: { file: WorkspacePage; isActive: boolean; depth: number }): JSX.Element {
    const { openPage } = useActions(workspaceLogic)
    return (
        <button
            type="button"
            onClick={() => openPage(file.path)}
            className={`w-full text-left flex items-center gap-2 px-2 py-1 rounded cursor-pointer ${
                isActive ? 'bg-accent-3000 text-text-primary' : 'hover:bg-fill-highlight-100 text-text-secondary'
            }`}
            style={{ paddingLeft: 8 + depth * 12 }}
        >
            <span className="text-text-tertiary">¶</span>
            <span className="truncate">{file.name}</span>
        </button>
    )
}

function FolderRow({
    folder,
    currentPath,
    onNewInFolder,
    depth,
}: {
    folder: WorkspaceFolder
    currentPath: string
    onNewInFolder: (folder: string) => void
    depth: number
}): JSX.Element {
    const [open, setOpen] = React.useState(true)
    return (
        <div>
            <div
                className="flex items-center gap-1 px-2 py-1 group rounded hover:bg-fill-highlight-100"
                style={{ paddingLeft: 8 + depth * 12 }}
            >
                <button
                    type="button"
                    onClick={() => setOpen((v) => !v)}
                    className="flex-1 text-left flex items-center gap-1 cursor-pointer"
                >
                    <span className="text-text-tertiary w-3 inline-block">{open ? '▾' : '▸'}</span>
                    <span className="font-medium">{folder.name}</span>
                </button>
                <button
                    type="button"
                    onClick={(e) => {
                        e.stopPropagation()
                        onNewInFolder(folder.path)
                    }}
                    className="opacity-0 group-hover:opacity-100 text-xs text-text-secondary hover:text-text-primary px-1 cursor-pointer"
                    title={`New page in ${folder.name}`}
                >
                    +
                </button>
            </div>
            {open && (
                <TreeNode folder={folder} currentPath={currentPath} onNewInFolder={onNewInFolder} depth={depth + 1} />
            )}
        </div>
    )
}

function EditorPane(): JSX.Element {
    const { currentPage } = useValues(workspaceLogic)
    const { updateBody, deletePage, renamePage } = useActions(workspaceLogic)

    if (!currentPage) {
        return (
            <section className="flex-1 flex items-center justify-center text-text-secondary">
                Select a page in the sidebar, or create a new one.
            </section>
        )
    }

    const handleRename = (): void => {
        const newName = window.prompt('Rename page:', currentPage.name)
        if (!newName || newName.trim() === currentPage.name) {
            return
        }
        renamePage(currentPage.path, newName.trim())
    }

    const handleDelete = (): void => {
        if (window.confirm(`Delete "${currentPage.name}"?`)) {
            deletePage(currentPage.path)
        }
    }

    return (
        <section className="flex-1 flex flex-col min-w-0">
            <header className="px-6 py-3 border-b border-border flex items-center justify-between bg-bg-light">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs text-text-tertiary truncate">{currentPage.folder || 'root'} /</span>
                    <span className="font-semibold truncate">{currentPage.name}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-text-secondary">
                    <button
                        type="button"
                        onClick={handleRename}
                        className="px-2 py-1 rounded border border-border hover:bg-fill-highlight-100 cursor-pointer"
                    >
                        Rename
                    </button>
                    <button
                        type="button"
                        onClick={handleDelete}
                        className="px-2 py-1 rounded border border-border hover:bg-fill-highlight-100 cursor-pointer text-danger"
                    >
                        Delete
                    </button>
                </div>
            </header>
            <div className="flex-1 flex min-h-0">
                <div className="flex-1 flex flex-col border-r border-border min-w-0">
                    <div className="text-[11px] uppercase tracking-wide text-text-tertiary px-6 pt-3">Markdown</div>
                    <textarea
                        value={currentPage.body}
                        onChange={(e) => updateBody(currentPage.path, e.target.value)}
                        className="flex-1 px-6 py-3 font-mono text-sm leading-relaxed bg-bg-light text-text-primary outline-none resize-none"
                        spellCheck={false}
                    />
                </div>
                <div className="flex-1 flex flex-col overflow-hidden min-w-0">
                    <div className="text-[11px] uppercase tracking-wide text-text-tertiary px-6 pt-3">Preview</div>
                    <div className="flex-1 overflow-y-auto px-6 py-3">
                        <MarkdownPreview body={currentPage.body} />
                    </div>
                </div>
            </div>
        </section>
    )
}

function MarkdownPreview({ body }: { body: string }): JSX.Element {
    const transformed = React.useMemo(
        () => body.replace(WIKI_RE, (_match, name: string) => `[${name}](wiki://${encodeURIComponent(name.trim())})`),
        [body]
    )
    return (
        <div className="prose prose-sm max-w-none">
            {/* eslint-disable-next-line react/forbid-elements */}
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                urlTransform={(url) => url}
                components={{
                    a: ({ href, children }) => {
                        if (href && href.startsWith('wiki://')) {
                            const name = decodeURIComponent(href.slice('wiki://'.length))
                            return <WikiLink name={name}>{children}</WikiLink>
                        }
                        return (
                            <Link to={href} target="_blank" targetBlankIcon>
                                {children}
                            </Link>
                        )
                    },
                }}
            >
                {transformed}
            </ReactMarkdown>
        </div>
    )
}

function WikiLink({ name, children }: { name: string; children: React.ReactNode }): JSX.Element {
    const { pagesByName } = useValues(workspaceLogic)
    const { openPage, createPage } = useActions(workspaceLogic)
    const match = pagesByName[name.toLowerCase()]
    const exists = !!match

    const handleClick = (e: React.MouseEvent): void => {
        e.preventDefault()
        if (exists && match) {
            openPage(match.path)
        } else {
            createPage(name)
        }
    }

    return (
        <Link
            onClick={handleClick}
            className={
                exists
                    ? 'text-link no-underline border-b border-link/40 hover:border-link cursor-pointer'
                    : 'text-danger border-b border-dashed border-danger/60 hover:border-danger cursor-pointer'
            }
            title={exists ? `Open "${match!.path}"` : `Create "${name}"`}
        >
            {children}
        </Link>
    )
}

export const scene: SceneExport = {
    component: FounderModeWorkspace,
    logic: workspaceLogic,
}

export default FounderModeWorkspace
