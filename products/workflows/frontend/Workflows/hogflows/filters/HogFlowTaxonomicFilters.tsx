import { useValues } from 'kea'

import { IconCode } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterRenderProps } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType } from '~/types'

import { workflowLogic } from '../../workflowLogic'

export const HogFlowTaxonomicFilters = ({
    onChange,
    infiniteListLogicProps,
}: Pick<TaxonomicFilterRenderProps, 'onChange' | 'infiniteListLogicProps'>): JSX.Element => {
    const { workflow } = useValues(workflowLogic)
    const { trimmedSearchQuery } = useValues(infiniteListLogic(infiniteListLogicProps))
    const variables = workflow?.variables || []

    if (!variables.length) {
        return <div className="p-2 text-muted">No workflow variables defined.</div>
    }

    const search = trimmedSearchQuery.toLowerCase()
    const filteredVariables = search
        ? variables.filter((variable: any) => {
              const key = variable.key?.toLowerCase() ?? ''
              const label = variable.label?.toLowerCase() ?? ''
              return key.includes(search) || label.includes(search)
          })
        : variables

    if (!filteredVariables.length) {
        return <div className="p-2 text-muted">No workflow variables match your search.</div>
    }

    return (
        <div className="flex flex-col gap-2 p-2">
            {filteredVariables.map((variable: any) => (
                <LemonButton
                    key={variable.key || variable.name}
                    size="small"
                    fullWidth
                    icon={<IconCode />}
                    onClick={() =>
                        onChange(variable.key, {
                            key: variable.key,
                            name: variable.key,
                            propertyFilterType: PropertyFilterType.WorkflowVariable,
                            taxonomicFilterGroup: TaxonomicFilterGroupType.WorkflowVariables,
                        })
                    }
                >
                    {variable.key}
                </LemonButton>
            ))}
        </div>
    )
}
