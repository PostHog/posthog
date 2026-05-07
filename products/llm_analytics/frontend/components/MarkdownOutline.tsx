import { router } from 'kea-router'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { slugifyHeading } from 'lib/lemon-ui/LemonMarkdown'

interface HeadingEntry {
    level: number
    text: string
    slug: string
}

interface HeadingTreeNode {
    heading: HeadingEntry
    children: HeadingTreeNode[]
}

export function parseMarkdownHeadings(markdown: string): HeadingEntry[] {
    const headings: HeadingEntry[] = []
    for (const line of markdown.split('\n')) {
        const match = /^(#{1,6})\s+(.+)$/.exec(line.trim())
        if (match) {
            const raw = match[2].trim()
            const textForSlug = raw.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
            headings.push({ level: match[1].length, text: raw, slug: slugifyHeading(textForSlug) })
        }
    }
    return headings
}

function buildHeadingTree(headings: HeadingEntry[]): HeadingTreeNode[] {
    const root: HeadingTreeNode[] = []
    const stack: HeadingTreeNode[] = []

    for (const heading of headings) {
        const node: HeadingTreeNode = { heading, children: [] }
        while (stack.length > 0 && stack[stack.length - 1].heading.level >= heading.level) {
            stack.pop()
        }
        if (stack.length === 0) {
            root.push(node)
        } else {
            stack[stack.length - 1].children.push(node)
        }
        stack.push(node)
    }
    return root
}

function collectNodeKeys(nodes: HeadingTreeNode[]): Set<string> {
    const keys = new Set<string>()
    for (const node of nodes) {
        if (node.children.length > 0) {
            keys.add(node.heading.slug)
            for (const key of collectNodeKeys(node.children)) {
                keys.add(key)
            }
        }
    }
    return keys
}

function OutlineNode({
    node,
    expandedNodes,
    toggleNode,
    onHeadingClick,
    depth,
    dataAttrPrefix,
}: {
    node: HeadingTreeNode
    expandedNodes: Set<string>
    toggleNode: (slug: string) => void
    onHeadingClick: (slug: string) => void
    depth: number
    dataAttrPrefix: string
}): JSX.Element {
    const hasChildren = node.children.length > 0
    const isNodeExpanded = expandedNodes.has(node.heading.slug)

    return (
        <li className="relative">
            {depth > 0 && <span className="absolute top-0 bottom-0 -left-[11px] border-l border-secondary/30" />}
            <div className="flex items-center gap-0.5">
                {hasChildren ? (
                    <button
                        type="button"
                        className="flex shrink-0 cursor-pointer items-center border-none bg-transparent p-0.5 text-muted hover:text-primary"
                        onClick={() => toggleNode(node.heading.slug)}
                        data-attr={`${dataAttrPrefix}-outline-toggle`}
                    >
                        <IconChevronRight
                            className={`h-3 w-3 transition-transform ${isNodeExpanded ? 'rotate-90' : ''}`}
                        />
                    </button>
                ) : (
                    <span className="w-4 shrink-0" />
                )}
                <button
                    type="button"
                    className="cursor-pointer truncate border-none bg-transparent py-0.5 text-left text-sm text-primary hover:text-link"
                    onClick={() => onHeadingClick(node.heading.slug)}
                    title={node.heading.text}
                    data-attr={`${dataAttrPrefix}-outline-heading`}
                >
                    {node.heading.text}
                </button>
            </div>
            {hasChildren && isNodeExpanded && (
                <ul className="m-0 ml-4 list-none border-l-0 pl-0">
                    {node.children.map((child, i) => (
                        <OutlineNode
                            key={i}
                            node={child}
                            expandedNodes={expandedNodes}
                            toggleNode={toggleNode}
                            onHeadingClick={onHeadingClick}
                            depth={depth + 1}
                            dataAttrPrefix={dataAttrPrefix}
                        />
                    ))}
                </ul>
            )}
        </li>
    )
}

export function MarkdownOutline({
    markdownText,
    containerRef,
    className,
    label,
    tooltipText,
    dataAttrPrefix,
    isExpanded,
    onToggleExpanded,
}: {
    markdownText: string
    containerRef: React.RefObject<HTMLDivElement | null>
    className?: string
    label: string
    tooltipText: string
    dataAttrPrefix: string
    isExpanded: boolean
    onToggleExpanded: () => void
}): JSX.Element | null {
    const headings = useMemo(() => parseMarkdownHeadings(markdownText), [markdownText])
    const tree = useMemo(() => buildHeadingTree(headings), [headings])
    const allExpandableKeys = useMemo(() => collectNodeKeys(tree), [tree])
    const [expandedNodes, setExpandedNodes] = useState<Set<string>>(() => new Set(allExpandableKeys))

    const toggleNode = useCallback((slug: string) => {
        setExpandedNodes((prev) => {
            const next = new Set(prev)
            if (next.has(slug)) {
                next.delete(slug)
            } else {
                next.add(slug)
            }
            return next
        })
    }, [])

    const expandAll = useCallback(() => setExpandedNodes(new Set(allExpandableKeys)), [allExpandableKeys])
    const collapseAll = useCallback(() => setExpandedNodes(new Set()), [])

    const handleHeadingClick = useCallback(
        (slug: string) => {
            const container = containerRef.current
            if (!container) {
                return
            }
            const target = container.querySelector(`#${CSS.escape(slug)}`)
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' })
                router.actions.replace(router.values.location.pathname, router.values.searchParams, `#${slug}`)
            }
        },
        [containerRef]
    )

    useEffect(() => {
        const scrollToHash = (): void => {
            const rawHash = window.location.hash.slice(1)
            if (!rawHash) {
                return
            }
            let slug: string
            try {
                slug = decodeURIComponent(rawHash)
            } catch {
                return
            }
            const container = containerRef.current
            if (!container) {
                return
            }
            const target = container.querySelector(`#${CSS.escape(slug)}`)
            if (target) {
                target.scrollIntoView({ block: 'start' })
            }
        }

        scrollToHash()
        window.addEventListener('hashchange', scrollToHash)
        return () => window.removeEventListener('hashchange', scrollToHash)
    }, [containerRef, markdownText])

    if (headings.length === 0) {
        return null
    }

    const allExpanded = expandedNodes.size >= allExpandableKeys.size

    return (
        <div className={`mb-3 rounded border bg-bg-light ${className ?? ''}`} data-attr={`${dataAttrPrefix}-outline`}>
            <div className="flex items-center justify-between px-3 py-2">
                <button
                    type="button"
                    className="flex cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-left text-xs font-semibold text-secondary"
                    onClick={onToggleExpanded}
                    data-attr={`${dataAttrPrefix}-outline-expand`}
                >
                    <IconChevronRight className={`h-3 w-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                    <Tooltip title={tooltipText}>
                        <span>{label}</span>
                    </Tooltip>
                    <span className="font-normal">({headings.length})</span>
                </button>
                {isExpanded && allExpandableKeys.size > 0 && (
                    <button
                        type="button"
                        className="cursor-pointer border-none bg-transparent p-0 text-xs text-muted hover:text-primary"
                        onClick={allExpanded ? collapseAll : expandAll}
                        data-attr={`${dataAttrPrefix}-outline-expand-all`}
                    >
                        {allExpanded ? 'Collapse all' : 'Expand all'}
                    </button>
                )}
            </div>
            {isExpanded && (
                <ul className="m-0 list-none border-t px-3 py-2">
                    {tree.map((node, i) => (
                        <OutlineNode
                            key={i}
                            node={node}
                            expandedNodes={expandedNodes}
                            toggleNode={toggleNode}
                            onHeadingClick={handleHeadingClick}
                            depth={0}
                            dataAttrPrefix={dataAttrPrefix}
                        />
                    ))}
                </ul>
            )}
        </div>
    )
}
