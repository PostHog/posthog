import type { ReactElement } from 'react'

import { Badge, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

export interface InviteEmailPreviewData {
    interviewee_identifier: string
    user_name: string
    email?: string | null
    subject: string
    html: string
    interview_url: string
    emailable: boolean
    is_preview_link: boolean
    _posthogUrl?: string
}

export interface InviteEmailPreviewViewProps {
    data: InviteEmailPreviewData
}

export function InviteEmailPreviewView({ data }: InviteEmailPreviewViewProps): ReactElement {
    return (
        <Card>
            <CardHeader>
                <CardTitle>{data.subject}</CardTitle>
                <div className="flex flex-col gap-1">
                    <span className="text-sm text-muted-foreground">
                        To {data.user_name}
                        {data.email ? ` <${data.email}>` : ''}
                    </span>
                    <div className="flex items-center gap-2 flex-wrap">
                        {!data.emailable && <Badge variant="warning">No email address — can&apos;t be sent</Badge>}
                        {data.is_preview_link && <Badge>Link is a placeholder until invites are sent</Badge>}
                    </div>
                </div>
            </CardHeader>
            <CardContent>
                {/* The HTML is server-rendered and sanitized at the source; render it isolated in a
                    sandboxed iframe (no scripts, no same-origin) as an extra layer of safety. */}
                <iframe
                    srcDoc={data.html}
                    sandbox=""
                    title="Invite email preview"
                    className="w-full border-0"
                    style={{ height: '70vh' }}
                />
            </CardContent>
        </Card>
    )
}
