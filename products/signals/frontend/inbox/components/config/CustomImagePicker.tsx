import { useValues } from 'kea'

import { LemonSelect, LemonTag } from '@posthog/lemon-ui'

import {
    type SignalsCustomImageOrigin,
    customImageChoices,
    signalsCustomImagesLogic,
} from '../../logics/signalsCustomImagesLogic'

interface CustomImagePickerProps {
    origin: SignalsCustomImageOrigin
    value: string | null
    onChange: (imageId: string | null) => void
    label: string
    description: string
    defaultLabel: string
    disabledReason?: string
    dataAttr: string
}

export function CustomImagePicker({
    origin,
    value,
    onChange,
    label,
    description,
    defaultLabel,
    disabledReason,
    dataAttr,
}: CustomImagePickerProps): JSX.Element | null {
    const { usableImages, imagesForbidden, originUnsupported } = useValues(signalsCustomImagesLogic({ origin }))
    const choices = customImageChoices(usableImages, imagesForbidden, value, originUnsupported)
    if (choices === null) {
        return null
    }

    return (
        <div className="flex items-center justify-between gap-4">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">{label}</span>
                <span className="text-[11.5px] text-muted">
                    {description} A run with a custom image starts on a larger sandbox, which costs more. If the image
                    can't be used, the run uses the standard image.
                </span>
            </div>
            <LemonSelect
                size="small"
                value={value}
                options={[
                    { value: null, label: defaultLabel },
                    ...choices.map((choice) => {
                        const tag = choice.status ? (
                            <LemonTag size="small" type={choice.status.type} className="shrink-0">
                                {choice.status.label}
                            </LemonTag>
                        ) : null
                        return {
                            value: choice.value,
                            label: (
                                <span className="flex items-center gap-1 max-w-32">
                                    <span className="truncate">{choice.name}</span>
                                    {tag}
                                </span>
                            ),
                            labelInMenu: (
                                <span className="flex items-center gap-1">
                                    {choice.name}
                                    {tag}
                                </span>
                            ),
                        }
                    }),
                ]}
                disabledReason={disabledReason}
                className="w-44 shrink-0"
                onChange={(next) => {
                    if (next !== value) {
                        onChange(next)
                    }
                }}
                aria-label={label}
                data-attr={dataAttr}
            />
        </div>
    )
}
