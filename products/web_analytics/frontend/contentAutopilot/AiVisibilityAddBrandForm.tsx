import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

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
                <LemonInput
                    size="small"
                    value={domain}
                    onChange={setDomain}
                    placeholder={placeholder}
                    aria-label="Domain"
                    className="w-72"
                    status={error ? 'danger' : undefined}
                    data-attr="ai-visibility-add-brand-domain"
                />
                {kinds.length > 1 ? (
                    <LemonSelect
                        size="small"
                        value={kind}
                        onChange={(value) => value && setKind(value)}
                        options={KIND_OPTIONS.filter((option) => kinds.includes(option.value))}
                        aria-label="Kind"
                        data-attr="ai-visibility-add-brand-kind"
                    />
                ) : null}
                <LemonButton
                    type="primary"
                    size="small"
                    htmlType="submit"
                    loading={adding}
                    disabledReason={disabledReason}
                    data-attr="ai-visibility-add-brand-submit"
                >
                    {kinds.length === 1 && kinds[0] === 'own' ? 'Set as your brand' : 'Add brand'}
                </LemonButton>
            </form>
            {error ? <p className="m-0 text-xs text-danger">{error}</p> : null}
        </div>
    )
}
