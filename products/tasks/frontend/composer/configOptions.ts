import type {
    AcpMessage,
    SessionConfigOption,
    SessionConfigOptionCategory,
    SessionConfigSelect,
    SessionConfigSelectGroup,
    SessionConfigSelectOption,
    SessionConfigSelectOptions,
} from '../conversation/acp-types'
import { isJsonRpcNotification } from '../conversation/acp-types'

/** Modes that hand the agent broad, unprompted access — hidden unless explicitly allowed. */
const BYPASS_MODE_VALUES = new Set(['bypassPermissions', 'full-access'])

export function isSelectGroup(options: SessionConfigSelectOptions): options is SessionConfigSelectGroup[] {
    return options.length > 0 && typeof options[0] === 'object' && 'options' in options[0]
}

/** Flatten grouped select options into a single array of leaf options. */
export function flattenSelectOptions(options: SessionConfigSelectOptions): SessionConfigSelectOption[] {
    if (!options.length) {
        return []
    }
    if (isSelectGroup(options)) {
        return options.flatMap((group) => group.options)
    }
    return options as SessionConfigSelectOption[]
}

export function getConfigOptionByCategory(
    configOptions: SessionConfigOption[] | undefined,
    category: SessionConfigOptionCategory
): SessionConfigOption | undefined {
    return configOptions?.find((opt) => opt.category === category)
}

export function asSelect(option: SessionConfigOption | undefined): SessionConfigSelect | undefined {
    return option && option.type === 'select' ? option : undefined
}

/**
 * Cycle to the next value of a mode select (used by the Shift+Tab shortcut).
 * Returns the next value, or undefined when cycling is not possible.
 */
export function cycleModeOption(
    modeOption: SessionConfigOption | undefined,
    options?: { allowBypassPermissions?: boolean }
): string | undefined {
    const select = asSelect(modeOption)
    if (!select) {
        return undefined
    }
    const all = flattenSelectOptions(select.options)
    const filtered = options?.allowBypassPermissions ? all : all.filter((opt) => !BYPASS_MODE_VALUES.has(opt.value))
    if (filtered.length === 0) {
        return undefined
    }
    const currentIndex = filtered.findIndex((opt) => opt.value === select.currentValue)
    if (currentIndex === -1) {
        return filtered[0]?.value
    }
    return filtered[(currentIndex + 1) % filtered.length]?.value
}

/** Filter bypass/full-access modes out of a mode select unless explicitly allowed. */
export function visibleModeOptions(
    select: SessionConfigSelect,
    allowBypassPermissions: boolean
): SessionConfigSelectOption[] {
    const all = flattenSelectOptions(select.options)
    return allowBypassPermissions ? all : all.filter((opt) => !BYPASS_MODE_VALUES.has(opt.value))
}

/**
 * Derive the latest session config options from the ACP event stream. The agent
 * re-emits the full option set on every `config_option_update`, so the last one
 * wins.
 */
export function deriveConfigOptions(events: AcpMessage[]): SessionConfigOption[] {
    let latest: SessionConfigOption[] | undefined
    for (const event of events) {
        const message = event.message
        if (!isJsonRpcNotification(message) || message.method !== 'session/update') {
            continue
        }
        const update = (
            message.params as { update?: { sessionUpdate?: string; configOptions?: SessionConfigOption[] } }
        )?.update
        if (update?.sessionUpdate === 'config_option_update' && Array.isArray(update.configOptions)) {
            latest = update.configOptions
        }
    }
    return latest ?? []
}
