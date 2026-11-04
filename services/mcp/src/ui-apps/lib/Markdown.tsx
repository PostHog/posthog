import { Fragment, type ReactElement, type ReactNode } from 'react'

import { Heading, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { type InlineToken, parseInline, parseMarkdown } from './markdown-parser'

function renderTokens(tokens: InlineToken[], onOpenLink: (url: string) => void): ReactNode[] {
    return tokens.map((token, key) => {
        switch (token.kind) {
            case 'text':
                return <Fragment key={key}>{token.text}</Fragment>
            case 'strong':
                return <strong key={key}>{renderTokens(token.children, onOpenLink)}</strong>
            case 'em':
                return <em key={key}>{renderTokens(token.children, onOpenLink)}</em>
            case 'code':
                return (
                    <code key={key} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
                        {token.text}
                    </code>
                )
            case 'link':
                return (
                    <a
                        key={key}
                        href={token.url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => {
                            e.preventDefault()
                            onOpenLink(token.url)
                        }}
                        className="text-link underline underline-offset-2"
                    >
                        {renderTokens(token.children, onOpenLink)}
                    </a>
                )
        }
    })
}

function renderInline(text: string, onOpenLink: (url: string) => void): ReactNode[] {
    return renderTokens(parseInline(text), onOpenLink)
}

/** Renders the Markdown subset that agent answers use, as React elements. It never injects HTML. */
export function Markdown({
    source,
    onOpenLink,
    className,
}: {
    source: string
    onOpenLink: (url: string) => void
    className?: string
}): ReactElement {
    return (
        <div className={`flex min-w-0 flex-col gap-3 break-words ${className ?? ''}`}>
            {parseMarkdown(source).map((block, index) => {
                switch (block.kind) {
                    case 'heading':
                        return (
                            <Heading key={index} size={block.level <= 2 ? 'base' : 'sm'} render={<h3 />}>
                                {renderInline(block.text, onOpenLink)}
                            </Heading>
                        )
                    case 'paragraph':
                        return (
                            <Text key={index} size="sm">
                                {renderInline(block.text, onOpenLink)}
                            </Text>
                        )
                    case 'list': {
                        const ListTag = block.ordered ? 'ol' : 'ul'
                        return (
                            <ListTag
                                key={index}
                                className={`flex flex-col gap-1 ps-5 text-sm ${block.ordered ? 'list-decimal' : 'list-disc'}`}
                            >
                                {block.items.map((item, itemIndex) => (
                                    <li key={itemIndex}>{renderInline(item, onOpenLink)}</li>
                                ))}
                            </ListTag>
                        )
                    }
                    case 'code':
                        return (
                            <pre
                                key={index}
                                className="overflow-x-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre"
                            >
                                <code>{block.text}</code>
                            </pre>
                        )
                    case 'table':
                        return (
                            <div key={index} className="overflow-x-auto rounded-md border">
                                <Table size="sm" fullWidth>
                                    <TableHeader>
                                        <TableRow>
                                            {block.header.map((cell, cellIndex) => (
                                                <TableHead key={cellIndex}>{renderInline(cell, onOpenLink)}</TableHead>
                                            ))}
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {block.rows.map((row, rowIndex) => (
                                            <TableRow key={rowIndex}>
                                                {row.map((cell, cellIndex) => (
                                                    <TableCell key={cellIndex}>
                                                        {renderInline(cell, onOpenLink)}
                                                    </TableCell>
                                                ))}
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        )
                }
            })}
        </div>
    )
}
