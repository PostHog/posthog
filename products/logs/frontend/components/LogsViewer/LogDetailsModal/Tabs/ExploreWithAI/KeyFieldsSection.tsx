import { IconInfo, IconSearch } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { KeyField } from './types'

export interface KeyFieldsSectionProps {
    fields: KeyField[]
    onApplyFilter?: (filterKey: string, filterValue: string, attributeType: 'log' | 'resource') => void
}

export function KeyFieldsSection({ fields, onApplyFilter }: KeyFieldsSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1 p-2">
            {fields.map((field, index) => (
                <div key={index} className="flex items-center gap-2 p-2 bg-bg-light rounded text-sm">
                    <span className="font-mono text-muted shrink-0">{field.field}:</span>
                    <CopyToClipboardInline explicitValue={field.value} className="font-mono truncate">
                        {field.value.length > 40 ? `${field.value.slice(0, 40)}...` : field.value}
                    </CopyToClipboardInline>
                    {onApplyFilter && (
                        <Tooltip title="Filter logs by this value">
                            <LemonButton
                                size="xsmall"
                                icon={<IconSearch />}
                                onClick={() =>
                                    onApplyFilter(
                                        field.field,
                                        field.value,
                                        field.attribute_type === 'resource' ? 'resource' : 'log'
                                    )
                                }
                            />
                        </Tooltip>
                    )}
                    <Tooltip title={field.significance}>
                        <IconInfo className="text-muted-alt shrink-0" />
                    </Tooltip>
                </div>
            ))}
        </div>
    )
}
