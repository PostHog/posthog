import { useMemo } from 'react'

import { IconCopy, IconDownload } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { renderBuildSpecMarkdown } from './buildSpecMarkdown'
import type { LandingPageBuildSpec } from './founderLandingPageLogic'

interface Props {
    spec: LandingPageBuildSpec
}

export function BuildSpecView({ spec }: Props): JSX.Element {
    // Render the markdown once — toolbar handlers reuse the same string for clipboard +
    // download so what the founder reads is exactly what they export.
    const markdown = useMemo(() => renderBuildSpecMarkdown(spec), [spec])

    const onCopy = async (): Promise<void> => {
        try {
            await navigator.clipboard.writeText(markdown)
            lemonToast.success(
                'Build spec copied to clipboard — paste into Claude Code, Cursor, or any markdown editor'
            )
        } catch {
            lemonToast.error('Could not access the clipboard — try Download instead')
        }
    }

    const onDownload = (): void => {
        const blob = new Blob([markdown], { type: 'text/markdown' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${slugify(spec.project_name) || 'landing-page'}-build-spec.md`
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
    }

    const totalSections = spec.page_sections.length
    const optionalIncluded = spec.page_sections.filter((s) => s.classification === 'optional_included').length
    const competitorCount = spec.competitor_profiles.length
    const coverageGapCount = spec.coverage_gaps.length

    return (
        <div className="flex flex-col gap-4">
            <LemonCard className="p-4">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div>
                        <h3 className="text-base font-semibold">Build spec for {spec.project_name}</h3>
                        <p className="text-sm text-text-secondary mt-1">
                            Hand to a developer or feed to an AI coding agent (Claude Code, Cursor) to build the actual
                            Next.js page.
                        </p>
                        <div className="flex flex-wrap gap-2 mt-3">
                            <LemonTag type="primary">{totalSections} sections</LemonTag>
                            {optionalIncluded > 0 && (
                                <LemonTag type="option">{optionalIncluded} optional added</LemonTag>
                            )}
                            <LemonTag type="option">{competitorCount} competitors profiled</LemonTag>
                            {coverageGapCount > 0 && (
                                <LemonTag type="warning">
                                    {coverageGapCount} coverage gap{coverageGapCount === 1 ? '' : 's'}
                                </LemonTag>
                            )}
                            <LemonTag type="option">brand: {spec.brand.source}</LemonTag>
                        </div>
                    </div>
                    <div className="flex gap-2">
                        <LemonButton size="small" icon={<IconCopy />} onClick={onCopy}>
                            Copy markdown
                        </LemonButton>
                        <LemonButton size="small" type="primary" icon={<IconDownload />} onClick={onDownload}>
                            Download .md
                        </LemonButton>
                    </div>
                </div>
            </LemonCard>

            <LemonCard className="p-6">
                <LemonMarkdown lowKeyHeadings={false} disableDocsRedirect>
                    {markdown}
                </LemonMarkdown>
            </LemonCard>
        </div>
    )
}

function slugify(s: string): string {
    return s
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60)
}
