import { useActions, useValues } from 'kea'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { EditorFilterProps } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

export function PathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const onChange = (pathGroupings: string[]): void => updateInsightFilter({ pathGroupings })

    if (quillSurface) {
        return (
            <TagsCombobox
                value={pathsFilter?.pathGroupings || []}
                onChange={(values) =>
                    onChange([
                        ...new Set(
                            values.flatMap((value) =>
                                value
                                    .split(',')
                                    .map((part) => part.trim())
                                    .filter(Boolean)
                            )
                        ),
                    ])
                }
                customValueNoun="wildcard"
            />
        )
    }

    return (
        <LemonInputSelect
            onChange={onChange}
            value={pathsFilter?.pathGroupings || []}
            disableFiltering
            mode="multiple"
            allowCustomValues
        />
    )
}
