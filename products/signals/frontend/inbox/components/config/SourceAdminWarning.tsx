import { IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { openInAppSupport } from 'lib/components/Support/openInAppSupport'

import { type SignalSourceConfig, SignalSourceProduct } from '../../types'

export function SourceAdminWarning({
    sourceConfigs,
    sourceProduct,
    label,
}: {
    sourceConfigs: SignalSourceConfig[] | null
    sourceProduct: SignalSourceProduct
    label?: string
}): JSX.Element | null {
    const configs = sourceConfigs?.filter((config) => config.source_product === sourceProduct) ?? []
    const disabledConfigs = configs.filter((config) => config.admin_disabled)
    if (sourceProduct === SignalSourceProduct.ReplayVision || disabledConfigs.length === 0) {
        return null
    }

    const warningLabel =
        disabledConfigs.length === configs.length
            ? `${label ?? 'Source'} disabled by PostHog`
            : 'Some signal types disabled by PostHog'

    return (
        <span className="inline-flex shrink-0 items-center gap-2 text-sm">
            {label && <span>{label}</span>}
            <Tooltip
                interactive
                openOnClick
                title={
                    <div className="flex max-w-xs flex-col gap-2">
                        <span className="font-semibold">{warningLabel}</span>
                        {[...new Set(disabledConfigs.map((config) => config.admin_disable_note).filter(Boolean))].map(
                            (note) => (
                                <span key={note} className="whitespace-pre-wrap">
                                    {note}
                                </span>
                            )
                        )}
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            onClick={() => openInAppSupport('self-driving-source-disabled')}
                            data-attr="signal-source-contact-support"
                        >
                            Contact support
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconWarning className="text-warning" />}
                    aria-label={warningLabel}
                    data-attr="signal-source-admin-disabled"
                />
            </Tooltip>
        </span>
    )
}
