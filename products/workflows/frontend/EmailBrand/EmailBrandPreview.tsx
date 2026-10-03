import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import type { EmailBrandStarterDesignApi } from '../generated/api.schemas'
import type { BrandDraft } from './utils'

function previewText(value: unknown): string {
    if (typeof value !== 'string') {
        return ''
    }
    const entities: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'" }
    return value
        .replace(/<[^>]*>/g, '')
        .replace(/&(?:amp|lt|gt|quot|#x27);/g, (entity) => entities[entity])
        .replace(/\{\{.*?\}\}/g, 'there')
}

export function EmailBrandPreview({
    draft,
    logoUrl,
    starter,
}: {
    draft: BrandDraft
    logoUrl: string | null
    starter?: EmailBrandStarterDesignApi | null
}): JSX.Element {
    const blocks =
        starter?.design.body.rows.flatMap((row) =>
            Array.isArray(row.columns)
                ? row.columns.flatMap(
                      (column: { contents?: { id: string; type: string; values: Record<string, unknown> }[] }) =>
                          column.contents ?? []
                  )
                : []
        ) ?? []
    return (
        <div className="min-w-0">
            <h3>Starter preview</h3>
            <LemonCard hoverEffect={false} className="p-0 overflow-hidden">
                {!starter ? (
                    <div className="p-6 space-y-4">
                        <LemonSkeleton className="h-8" />
                        <LemonSkeleton className="h-24" />
                        <LemonSkeleton className="h-8 w-32" />
                    </div>
                ) : (
                    <div
                        className="p-6 ph-no-capture"
                        style={{
                            backgroundColor: draft.background_color,
                            color: draft.text_color,
                            fontFamily: draft.font_stack,
                            borderTop: `4px solid ${draft.accent_color}`,
                        }}
                        data-attr="email-brand-live-preview"
                    >
                        {blocks.map((block) =>
                            block.type === 'image' ? (
                                <div key={block.id} className="text-center mb-6">
                                    <img
                                        src={logoUrl ?? undefined}
                                        alt={draft.name}
                                        className="max-w-40 max-h-32 object-contain"
                                    />
                                </div>
                            ) : block.type === 'heading' ? (
                                <h2
                                    key={block.id}
                                    className={
                                        block.id === 'brand-starter-name'
                                            ? 'text-center text-2xl mb-6 break-words'
                                            : 'text-2xl mb-3'
                                    }
                                >
                                    {previewText(block.values.text)}
                                </h2>
                            ) : block.type === 'button' ? (
                                <span
                                    key={block.id}
                                    className="inline-block rounded px-6 py-3 mb-8 font-semibold"
                                    style={{
                                        backgroundColor: draft.primary_color,
                                        color: (block.values.buttonColors as { color?: string })?.color,
                                    }}
                                >
                                    {previewText(block.values.text)}
                                </span>
                            ) : block.type === 'custom' ? (
                                <p key={block.id} className="text-center text-xs mb-0">
                                    {previewText(block.values.unsubscribe_link_content)}
                                </p>
                            ) : (
                                <p key={block.id} className="mb-5 leading-relaxed break-words">
                                    {previewText(block.values.text)}
                                </p>
                            )
                        )}
                    </div>
                )}
            </LemonCard>
            <p className="text-xs text-secondary mt-2">
                This starter is a snapshot. Later brand changes won't change existing templates. Your email app may use
                the fallback font.
            </p>
        </div>
    )
}
