import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { llmAnalyticsReviewsLogic, type LLMAnalyticsReviewsLogicProps } from './llmAnalyticsReviewsLogic'
import {
    REVIEW_EXPORT_MAX_ROWS,
    copyReviewsToCsv,
    copyReviewsToExcel,
    copyReviewsToJson,
    downloadReviewsAsCsv,
    fetchAllReviewsForExport,
} from './reviewExportUtils'
import type { TraceReview } from './types'

type CopyFn = (reviews: TraceReview[]) => void

export function LLMAnalyticsReviewsExport({ tabId }: LLMAnalyticsReviewsLogicProps): JSX.Element {
    const { filters } = useValues(llmAnalyticsReviewsLogic({ tabId }))
    const { startExport } = useActions(exportsLogic)

    const [isBusy, setIsBusy] = useState(false)

    const runExport = async (onReviews: (reviews: TraceReview[]) => void, notice?: string): Promise<void> => {
        if (isBusy) {
            return
        }

        setIsBusy(true)
        try {
            const { reviews, truncated } = await fetchAllReviewsForExport({
                search: filters.search || undefined,
                definition_id: filters.definition_id || undefined,
                order_by: filters.order_by,
            })

            if (reviews.length === 0) {
                lemonToast.info('No reviews to export with the current filters.')
                return
            }

            onReviews(reviews)

            if (notice) {
                lemonToast.success(notice)
            }

            if (truncated) {
                lemonToast.warning(
                    `Export truncated to the first ${REVIEW_EXPORT_MAX_ROWS.toLocaleString()} reviews. Refine your filters to export the rest.`
                )
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            lemonToast.error(`Export failed: ${message}`)
        } finally {
            setIsBusy(false)
        }
    }

    const exportCsv = (): Promise<void> => runExport((reviews) => downloadReviewsAsCsv(reviews, startExport))
    const copyToClipboardWith =
        (fn: CopyFn): (() => Promise<void>) =>
        () =>
            runExport(fn)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Export current columns',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                void exportCsv()
                            },
                            disabledReason: isBusy ? 'Preparing export…' : undefined,
                            'data-attr': 'llma-trace-reviews-export-csv',
                        },
                    ],
                },
                {
                    label: 'Copy to clipboard',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                void copyToClipboardWith(copyReviewsToCsv)()
                            },
                            disabledReason: isBusy ? 'Preparing copy…' : undefined,
                            'data-attr': 'llma-trace-reviews-copy-csv',
                        },
                        {
                            label: 'JSON',
                            onClick: () => {
                                void copyToClipboardWith(copyReviewsToJson)()
                            },
                            disabledReason: isBusy ? 'Preparing copy…' : undefined,
                            'data-attr': 'llma-trace-reviews-copy-json',
                        },
                        {
                            label: 'Excel',
                            onClick: () => {
                                void copyToClipboardWith(copyReviewsToExcel)()
                            },
                            disabledReason: isBusy ? 'Preparing copy…' : undefined,
                            'data-attr': 'llma-trace-reviews-copy-excel',
                        },
                    ],
                },
            ]}
        >
            <LemonButton
                type="secondary"
                icon={<IconDownload />}
                size="small"
                loading={isBusy}
                data-attr="llma-trace-reviews-export-menu"
            >
                Export
            </LemonButton>
        </LemonMenu>
    )
}
