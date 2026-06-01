'use client'

import { FileUpIcon, LoaderCircleIcon } from 'lucide-react'
import { useRef, useState } from 'react'

import { RegistryApiError, createSkillTemplate } from '@/lib/registryClient'
import { buildSkills, readDataTransfer, toCreateBody } from '@/lib/skillUpload'

type Status =
    | { kind: 'idle' }
    | { kind: 'busy'; message: string }
    | { kind: 'ok'; message: string }
    | { kind: 'error'; message: string }

/**
 * Drop target for the Skills tab. Accepts a skill folder (with `SKILL.md`)
 * or a `.zip`, parses it client-side, and creates one template per skill
 * via the registry API. Calls `onUploaded` after a successful batch so the
 * list refetches.
 */
export function SkillDropzone({
    teamId,
    onUploaded,
    children,
}: {
    teamId: number
    onUploaded: () => void
    children: React.ReactNode
}): React.ReactElement {
    const [dragging, setDragging] = useState(false)
    const [status, setStatus] = useState<Status>({ kind: 'idle' })
    // Drag events fire on every child; count enter/leave so the highlight
    // doesn't flicker as the pointer crosses nested elements.
    const dragDepth = useRef(0)

    const busy = status.kind === 'busy'

    async function handleDrop(e: React.DragEvent): Promise<void> {
        e.preventDefault()
        dragDepth.current = 0
        setDragging(false)
        if (busy) {
            return
        }

        setStatus({ kind: 'busy', message: 'Reading dropped files…' })
        let created = 0
        let total = 0
        const names: string[] = []
        try {
            const files = await readDataTransfer(e.dataTransfer)
            const skills = buildSkills(files)
            total = skills.length
            for (const skill of skills) {
                setStatus({ kind: 'busy', message: `Uploading ${created + 1}/${total}…` })
                await createSkillTemplate(teamId, toCreateBody(skill))
                created += 1
                names.push(skill.name)
            }
            setStatus({
                kind: 'ok',
                message: `Uploaded ${created} skill${created === 1 ? '' : 's'}: ${names.join(', ')}`,
            })
        } catch (err) {
            // A mid-batch failure leaves earlier skills created — report the
            // partial result rather than implying nothing happened.
            const detail = messageOf(err)
            setStatus({
                kind: 'error',
                message:
                    created > 0 ? `Uploaded ${created}/${total} (${names.join(', ')}), then failed: ${detail}` : detail,
            })
        } finally {
            // Refresh the list whenever anything landed, including partial batches.
            if (created > 0) {
                onUploaded()
            }
        }
    }

    return (
        <div
            onDragEnter={(e) => {
                e.preventDefault()
                dragDepth.current += 1
                setDragging(true)
            }}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={(e) => {
                e.preventDefault()
                dragDepth.current -= 1
                if (dragDepth.current <= 0) {
                    setDragging(false)
                }
            }}
            onDrop={handleDrop}
            className="relative"
        >
            <div
                className={
                    'mb-3 flex items-center gap-2 rounded-md border border-dashed p-2.5 text-xs transition-colors ' +
                    (dragging
                        ? 'border-info-foreground/60 bg-info/20 text-info-foreground'
                        : 'border-border text-muted-foreground')
                }
            >
                {busy ? (
                    <LoaderCircleIcon className="h-3.5 w-3.5 animate-spin" />
                ) : (
                    <FileUpIcon className="h-3.5 w-3.5" />
                )}
                <span>
                    Drag an Agent Skills folder or <code className="font-mono">.zip</code> file here to upload.
                </span>
            </div>

            {status.kind !== 'idle' && status.kind !== 'busy' ? (
                <div
                    role="status"
                    className={
                        'mb-3 rounded-md border px-2.5 py-1.5 text-xs ' +
                        (status.kind === 'ok'
                            ? 'border-success-foreground/30 bg-success/20 text-success-foreground'
                            : 'border-destructive-foreground/30 bg-destructive/15 text-destructive-foreground')
                    }
                >
                    {status.message}
                </div>
            ) : null}

            {children}

            {dragging ? (
                <div className="pointer-events-none absolute inset-0 rounded-md border-2 border-info-foreground/60 bg-info/10" />
            ) : null}
        </div>
    )
}

function messageOf(err: unknown): string {
    if (err instanceof RegistryApiError) {
        return err.message
    }
    return err instanceof Error ? err.message : 'Upload failed.'
}
