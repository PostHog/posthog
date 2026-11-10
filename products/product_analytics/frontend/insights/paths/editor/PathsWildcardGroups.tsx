import { useActions, useValues } from 'kea'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { EditorFilterProps } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

const NON_ESCAPED_COMMA = /(?<!\\),/

export function PathsWildcardGroups({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const onChange = (pathGroupings: string[]): void => updateInsightFilter({ pathGroupings })

    if (quillSurface) {
        const current = pathsFilter?.pathGroupings || []
        return (
            <TagsCombobox
                value={current}
                onChange={(values) =>
                    onChange([
                        ...new Set(
                            values.flatMap((value) =>
                                current.includes(value)
                                    ? [value]
                                    : value
                                          .split(NON_ESCAPED_COMMA)
                                          .map((part) => part.replaceAll('\\,', ',').trim())
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
