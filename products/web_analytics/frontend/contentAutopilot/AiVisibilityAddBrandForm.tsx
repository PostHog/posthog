import { useActions, useValues } from 'kea'

import { Button, Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { AddableBrandKind, aiVisibilityAddBrandLogic } from './aiVisibilityAddBrandLogic'

const KIND_OPTIONS: { value: AddableBrandKind; label: string }[] = [
    { value: 'own', label: 'Your brand' },
    { value: 'competitor', label: 'Competitor' },
]

export interface AiVisibilityAddBrandFormProps {
    formKey: string
    kinds: AddableBrandKind[]
    placeholder?: string
}

export const AiVisibilityAddBrandForm = ({
    formKey,
    kinds,
    placeholder = 'example.com',
}: AiVisibilityAddBrandFormProps): JSX.Element => {
    const logic = aiVisibilityAddBrandLogic({ formKey, defaultKind: kinds[0] })
    const { domain, kind, adding, error, disabledReason } = useValues(logic)
    const { setDomain, setKind, addBrand } = useActions(logic)
    const options = KIND_OPTIONS.filter((option) => kinds.includes(option.value))

    return (
        <div className="flex flex-col gap-1" data-attr="ai-visibility-add-brand">
            <form
                className="flex flex-wrap items-center gap-2"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!disabledReason) {
                        addBrand()
                    }
                }}
            >
                <Input
                    size="sm"
                    value={domain}
                    onChange={(event) => setDomain(event.target.value)}
                    placeholder={placeholder}
                    aria-label="Domain"
                    aria-invalid={!!error}
                    className="w-72 max-w-full"
                    data-attr="ai-visibility-add-brand-domain"
                />
                {options.length > 1 ? (
                    <Select<AddableBrandKind> value={kind} onValueChange={(value) => value && setKind(value)}>
                        <SelectTrigger size="sm" aria-label="Kind" data-attr="ai-visibility-add-brand-kind">
                            <SelectValue>
                                {(value: AddableBrandKind | null) =>
                                    options.find((option) => option.value === value)?.label
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {options.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                ) : null}
                <Button
                    variant="primary"
                    type="submit"
                    loading={adding}
                    disabledReason={disabledReason}
                    data-attr="ai-visibility-add-brand-submit"
                >
                    {kinds.length === 1 && kinds[0] === 'own' ? 'Set as your brand' : 'Add brand'}
                </Button>
            </form>
            {error ? (
                <Text size="xs" render={<p className="m-0 text-destructive-foreground" />}>
                    {error}
                </Text>
            ) : null}
        </div>
    )
}
