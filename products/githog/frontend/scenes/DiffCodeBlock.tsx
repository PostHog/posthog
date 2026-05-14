import { toHtml } from 'hast-util-to-html'
import { useValues } from 'kea'
import { common, createLowlight } from 'lowlight'
import { useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

// Reuse the same set of languages CodeSnippet ships — `common` already bundles
// the everyday ones (python, js, ts, json, yaml, go, java, etc.). We register
// our own instance here so we can highlight the per-line *body* of a unified
// diff in its source language while preserving the +/- prefix coloring.
const lowlight = createLowlight(common)

// Map common filename extensions to highlight.js language keys. Anything we
// don't know falls back to highlightAuto which is usually good enough.
const EXTENSION_LANG: Record<string, string> = {
    py: 'python',
    pyi: 'python',
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    md: 'markdown',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    sql: 'sql',
    rs: 'rust',
    go: 'go',
    java: 'java',
    kt: 'kotlin',
    swift: 'swift',
    rb: 'ruby',
    php: 'php',
    cs: 'csharp',
    cpp: 'cpp',
    cc: 'cpp',
    cxx: 'cpp',
    c: 'c',
    h: 'c',
    hpp: 'cpp',
    css: 'css',
    scss: 'scss',
    less: 'less',
    html: 'xml',
    xml: 'xml',
    svg: 'xml',
    toml: 'ini',
    ini: 'ini',
    env: 'bash',
    dockerfile: 'dockerfile',
    makefile: 'makefile',
}

function languageForFilename(filename: string | undefined): string | null {
    if (!filename) {
        return null
    }
    const lower = filename.toLowerCase()
    if (lower.endsWith('dockerfile') || lower === 'dockerfile') {
        return 'dockerfile'
    }
    if (lower.endsWith('makefile') || lower === 'makefile') {
        return 'makefile'
    }
    const ext = lower.split('.').pop() || ''
    return EXTENSION_LANG[ext] || null
}

type DiffLineKind = 'add' | 'remove' | 'hunk' | 'meta' | 'ctx'

function classifyLine(line: string): { kind: DiffLineKind; prefix: string; body: string } {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) {
        return { kind: 'meta', prefix: '', body: line }
    }
    if (line.startsWith('@@')) {
        return { kind: 'hunk', prefix: '', body: line }
    }
    if (line.startsWith('+')) {
        return { kind: 'add', prefix: '+', body: line.slice(1) }
    }
    if (line.startsWith('-')) {
        return { kind: 'remove', prefix: '-', body: line.slice(1) }
    }
    return { kind: 'ctx', prefix: line.startsWith(' ') ? ' ' : '', body: line.startsWith(' ') ? line.slice(1) : line }
}

function highlight(body: string, lang: string | null): string {
    if (!body) {
        return ''
    }
    if (lang && lowlight.registered(lang)) {
        return toHtml(lowlight.highlight(lang, body))
    }
    return toHtml(lowlight.highlightAuto(body))
}

function lineBgClass(kind: DiffLineKind): string {
    switch (kind) {
        case 'add':
            return 'bg-[rgba(34,197,94,0.10)]'
        case 'remove':
            return 'bg-[rgba(239,68,68,0.10)]'
        case 'hunk':
            return 'bg-[rgba(59,130,246,0.10)]'
        default:
            return ''
    }
}

function prefixColorClass(kind: DiffLineKind): string {
    switch (kind) {
        case 'add':
            return 'text-success'
        case 'remove':
            return 'text-danger'
        case 'hunk':
            return 'text-muted'
        default:
            return 'text-muted'
    }
}

export function DiffCodeBlock({ patch, filename }: { patch: string; filename?: string }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const language = useMemo(() => languageForFilename(filename), [filename])
    const lines = useMemo(() => patch.split('\n'), [patch])

    return (
        <pre
            className={`m-0 p-0 rounded border border-border overflow-auto ${isDarkModeOn ? 'hljs-dark' : ''}`}
            style={{ fontSize: '0.78rem', lineHeight: '1.4' }}
        >
            <code className="hljs block">
                {lines.map((line, idx) => {
                    const { kind, prefix, body } = classifyLine(line)
                    const bodyHtml = kind === 'meta' || kind === 'hunk' ? '' : highlight(body || ' ', language)
                    return (
                        <div key={idx} className={`flex ${lineBgClass(kind)} px-2`}>
                            <span
                                className={`inline-block w-3 shrink-0 select-none ${prefixColorClass(kind)}`}
                                aria-hidden="true"
                            >
                                {prefix || ' '}
                            </span>
                            {kind === 'meta' || kind === 'hunk' ? (
                                <span className={`${prefixColorClass(kind)} font-mono`}>{body}</span>
                            ) : (
                                <span
                                    className="font-mono"
                                    // bodyHtml already escaped by lowlight + hast-util-to-html
                                    dangerouslySetInnerHTML={{ __html: bodyHtml }}
                                />
                            )}
                        </div>
                    )
                })}
            </code>
        </pre>
    )
}
