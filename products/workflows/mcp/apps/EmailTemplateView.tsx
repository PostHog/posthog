import type { ReactElement } from 'react'

import { Badge, Button, Card, CardContent } from '@posthog/quill'

export interface EmailTemplateEmail {
    subject?: string
    text?: string
    html?: string
    design?: Record<string, unknown>
}

export interface EmailTemplateData {
    id: string
    name: string
    description?: string | null
    type?: string
    content?: {
        templating?: string
        email?: EmailTemplateEmail | null
    } | null
    _posthogUrl?: string
}

export interface EmailTemplateViewProps {
    template: EmailTemplateData
}

export function EmailTemplateView({ template }: EmailTemplateViewProps): ReactElement {
    const email = template.content?.email ?? undefined
    const html = email?.html
    const templating = template.content?.templating

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{template.name}</span>
                        {template.type && <Badge>{template.type}</Badge>}
                        {templating && <Badge variant="info">{templating}</Badge>}
                    </div>
                    {template.description && (
                        <span className="text-sm text-muted-foreground">{template.description}</span>
                    )}
                </div>

                {email?.subject && (
                    <div className="flex items-baseline gap-2">
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">Subject</span>
                        <span className="text-sm font-medium">{email.subject}</span>
                    </div>
                )}

                <Card>
                    <CardContent className="p-0 overflow-hidden">
                        {html ? (
                            // srcDoc keeps the email self-contained; omitting allow-scripts neutralises any
                            // <script> in the template html.
                            <iframe
                                srcDoc={html}
                                sandbox="allow-same-origin"
                                title={`Preview of ${template.name}`}
                                className="w-full h-[640px] border-0 bg-white"
                            />
                        ) : email?.text ? (
                            <pre className="whitespace-pre-wrap p-4 text-sm text-foreground">{email.text}</pre>
                        ) : (
                            <div className="p-4 text-sm text-muted-foreground">
                                No preview available for this template.
                            </div>
                        )}
                    </CardContent>
                </Card>

                {template._posthogUrl && (
                    <div>
                        <Button
                            variant="link"
                            size="sm"
                            render={<a href={template._posthogUrl} target="_blank" rel="noreferrer" />}
                        >
                            Open in editor
                        </Button>
                    </div>
                )}
            </div>
        </div>
    )
}
