import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { notebookFilterLogic } from './notebookFilterLogic'

export function NotebookFiltersBar(): JSX.Element | null {
    const { shortId, mode, isShared } = useValues(notebookLogic)
    const logic = notebookFilterLogic({ shortId })
    const { filters } = useValues(logic)
    const { setFilters } = useActions(logic)
    if (isShared || mode === 'canvas') {
        return null
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
            {filters && (
                <LemonButton size="small" onClick={() => setFilters(null)}>
                    Clear notebook filters
                </LemonButton>
            )}
        </div>
    )
}
