import { JSX } from 'react'

import {
    IconBrain,
    IconChevronDown,
    IconEye,
    IconLock,
    IconPause,
    IconPencil,
    IconShieldLock,
    IconSparkles,
} from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { SessionConfigOption, SessionConfigSelect, SessionConfigSelectOption } from '../conversation/acp-types'
import { asSelect, flattenSelectOptions, visibleModeOptions } from './configOptions'

interface ConfigSelectProps {
    option: SessionConfigSelect
    options: SessionConfigSelectOption[]
    onChange: (value: string) => void
    icon: JSX.Element
    fallbackLabel: string
    disabled?: boolean
    /** Prefix shown before the current value, e.g. "Effort". */
    prefix?: string
}

/** Shared dropdown that maps an ACP select config option onto a LemonMenu. */
function ConfigSelect({
    option,
    options,
    onChange,
    icon,
    fallbackLabel,
    disabled,
    prefix,
}: ConfigSelectProps): JSX.Element | null {
    if (options.length === 0) {
        return null
    }
    const currentLabel =
        options.find((opt) => opt.value === option.currentValue)?.name ?? option.currentValue ?? fallbackLabel
    const activeIndex = options.findIndex((opt) => opt.value === option.currentValue)

    return (
        <LemonMenu
            items={options.map((opt) => ({
                label: opt.name,
                onClick: () => onChange(opt.value),
                active: opt.value === option.currentValue,
                tooltip: opt.description ?? undefined,
            }))}
            activeItemIndex={activeIndex}
            placement="top-start"
        >
            <LemonButton size="xsmall" type="tertiary" icon={icon} disabled={disabled} sideIcon={<IconChevronDown />}>
                {prefix ? `${prefix}: ${currentLabel}` : currentLabel}
            </LemonButton>
        </LemonMenu>
    )
}

const MODE_ICONS: Record<string, JSX.Element> = {
    plan: <IconPause className="text-warning" />,
    default: <IconPencil />,
    acceptEdits: <IconShieldLock className="text-success" />,
    bypassPermissions: <IconLock className="text-danger" />,
    'full-access': <IconLock className="text-danger" />,
    'read-only': <IconEye className="text-warning" />,
    auto: <IconSparkles className="text-accent" />,
}

export function ModeSelector({
    modeOption,
    onChange,
    allowBypassPermissions = false,
    disabled,
}: {
    modeOption: SessionConfigOption | undefined
    onChange: (value: string) => void
    allowBypassPermissions?: boolean
    disabled?: boolean
}): JSX.Element | null {
    const select = asSelect(modeOption)
    if (!select) {
        return null
    }
    const options = visibleModeOptions(select, allowBypassPermissions)
    const icon = MODE_ICONS[select.currentValue] ?? <IconPencil />
    return (
        <ConfigSelect
            option={select}
            options={options}
            onChange={onChange}
            icon={icon}
            fallbackLabel="Mode"
            disabled={disabled}
        />
    )
}

export function ModelSelector({
    modelOption,
    onChange,
    disabled,
}: {
    modelOption: SessionConfigOption | undefined
    onChange: (value: string) => void
    disabled?: boolean
}): JSX.Element | null {
    const select = asSelect(modelOption)
    if (!select) {
        return null
    }
    return (
        <ConfigSelect
            option={select}
            options={flattenSelectOptions(select.options)}
            onChange={onChange}
            icon={<IconSparkles />}
            fallbackLabel="Model"
            disabled={disabled}
        />
    )
}

export function ReasoningEffortSelector({
    thoughtOption,
    onChange,
    disabled,
}: {
    thoughtOption: SessionConfigOption | undefined
    onChange: (value: string) => void
    disabled?: boolean
}): JSX.Element | null {
    const select = asSelect(thoughtOption)
    if (!select) {
        return null
    }
    return (
        <ConfigSelect
            option={select}
            options={flattenSelectOptions(select.options)}
            onChange={onChange}
            icon={<IconBrain />}
            fallbackLabel="Effort"
            prefix="Effort"
            disabled={disabled}
        />
    )
}
