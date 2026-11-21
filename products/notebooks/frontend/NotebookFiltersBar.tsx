import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { NotebookNodeLogicProps } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { isSavedInsightNode } from '~/queries/utils'

import { notebookFilterLogic } from './notebookFilterLogic'
import { getFilteredNotebookQuery } from './notebookFilters'

function isFilterableBlock({ nodeType, attributes }: NotebookNodeLogicProps): boolean {
    if (nodeType === NotebookNodeType.RecordingPlaylist) {
        return true
    }
    return (
        nodeType === NotebookNodeType.Query &&
        (!!attributes.id ||
            isSavedInsightNode(attributes.query) ||
            !!getFilteredNotebookQuery(attributes.query, { properties: [] }))
    )
}

export function NotebookFiltersBar(): JSX.Element | null {
    const { shortId, mode, isShared, nodeLogics } = useValues(notebookLogic)
    const logic = notebookFilterLogic({ shortId })
    const { filters } = useValues(logic)
    const { setFilters } = useActions(logic)
    if (isShared || mode === 'canvas') {
        return null
    }

    const clearFiltersButton = filters && (
        <LemonButton size="small" onClick={() => setFilters(null)}>
            Clear notebook filters
        </LemonButton>
    )
    if (!Object.values(nodeLogics).some((node) => isFilterableBlock(node.props))) {
        return clearFiltersButton
    }

    return (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Notebook filters">
            <DateFilter
                size="small"
                showCustom
                placeholder="Date range"
                dateFrom={filters?.dateRange?.date_from}
                dateTo={filters?.dateRange?.date_to}
                footerComponent={
                    filters?.dateRange
                        ? (close) => (
                              <LemonButton
                                  fullWidth
                                  size="small"
                                  onClick={() => {
                                      setFilters({ properties: filters.properties })
                                      close()
                                  }}
                              >
                                  Use each block’s date range
                              </LemonButton>
                          )
                        : undefined
                }
                onChange={(date_from, date_to) =>
                    setFilters({ properties: filters?.properties ?? [], dateRange: { date_from, date_to } })
                }
            />
            <PropertyFilters
                pageKey={`notebook-filters-${shortId}`}
                propertyFilters={filters?.properties}
                onChange={(properties) => setFilters({ ...filters, properties })}
                buttonSize="small"
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Cohorts,
                ]}
            />
            {clearFiltersButton}
        </div>
    )
}
