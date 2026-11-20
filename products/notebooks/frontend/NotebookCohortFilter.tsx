import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { notebookCohortFilterLogic } from './notebookCohortFilterLogic'

export function NotebookCohortFilter(): JSX.Element {
    const { shortId } = useValues(notebookLogic)
    const logic = notebookCohortFilterLogic({ shortId })
    const { previewCohort } = useValues(logic)
    const { setPreviewCohort } = useActions(logic)
    const [open, setOpen] = useState(false)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonButton
                size="small"
                icon={<IconFilter />}
                data-attr="notebook-preview-cohort"
                onClick={() => {
                    posthog.capture('notebook cohort picker opened', { notebook_id: shortId })
                    setOpen(true)
                }}
            >
                {previewCohort ? previewCohort.name : 'Filter by cohort'}
            </LemonButton>
            {previewCohort && (
                <>
                    <LemonButton size="small" onClick={() => setPreviewCohort(null)}>
                        Clear filter
                    </LemonButton>
                    <span className="text-xs text-secondary">
                        Only blocks labeled “Cohort preview” use this filter.
                    </span>
                </>
            )}
            <LemonModal title="Filter by cohort" isOpen={open} onClose={() => setOpen(false)}>
                {open && (
                    <TaxonomicFilter
                        groupType={TaxonomicFilterGroupType.Cohorts}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                        onChange={(group, value, item) => {
                            const id = Number(value)
                            if (Number.isSafeInteger(id) && id > 0) {
                                setPreviewCohort({ id, name: group.getName?.(item) || String(id) })
                                setOpen(false)
                            }
                        }}
                    />
                )}
            </LemonModal>
        </div>
    )
}
