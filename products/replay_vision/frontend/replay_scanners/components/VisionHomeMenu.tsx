import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronDown, IconPiggyBank, IconPlus, IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, type LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import type { ScannerStatus } from '../scannerStatus'
import type { ReplayScanner } from '../types'
import { isProblemStatus, visionHomeLogic, type VisionHomeView } from '../visionHomeLogic'
import { ScannerStatusLabel, statusTone, TONE_DOT } from './ScannerStatusLabel'

function StatusDot({ status }: { status: ScannerStatus | undefined }): JSX.Element {
    return (
        <span
            className={`size-2 shrink-0 rounded-full ${status ? TONE_DOT[statusTone(status)] : 'bg-muted'}`}
            aria-hidden
        />
    )
}

function Count({ value, title }: { value: number | undefined; title: string }): JSX.Element | null {
    return value ? (
        <span className="text-xs font-normal tabular-nums text-secondary" title={title}>
            {value}
        </span>
    ) : null
}

const COUNT_TITLE = 'Highlights from the last 7 days'

export const MIN_SCANNER_TABS = 2
export const MAX_SCANNER_TABS = 5

// Literal class names, so Tailwind finds them. Tab i shows once the bar is at least TAB_SHOWN[i] wide, and the
// More menu for k tabs shows only while exactly k tabs fit. Names truncate, so each tab has a known maximum width, and
// every cutoff leaves room for More to show the name of a scanner picked from it.
const TAB_SHOWN = ['flex', 'flex', 'hidden @[66rem]:flex', 'hidden @[78rem]:flex', 'hidden @[90rem]:flex']
const MORE_SHOWN_UNTIL_NEXT = [
    'flex',
    'flex',
    'flex @[66rem]:hidden',
    'hidden @[66rem]:flex @[78rem]:hidden',
    'hidden @[78rem]:flex @[90rem]:hidden',
]
const MORE_SHOWN_FROM = ['flex', 'flex', 'flex', 'hidden @[66rem]:flex', 'hidden @[78rem]:flex', 'hidden @[90rem]:flex']

function moveFocus(event: React.KeyboardEvent<HTMLElement>): void {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') {
        return
    }
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[data-home-menu-item]')).filter(
        (element) => element.offsetParent !== null
    )
    const index = items.indexOf(document.activeElement as HTMLElement)
    if (index === -1) {
        return
    }
    event.preventDefault()
    items[(index + (event.key === 'ArrowRight' ? 1 : items.length - 1)) % items.length].focus()
}

export function VisionHomeMenu(): JSX.Element {
    const { view, pickerScanners, scannerStatuses, highlightCounts } = useValues(visionHomeLogic)
    const { setView } = useActions(visionHomeLogic)

    const select = (next: VisionHomeView, kind: string, inOverflow = false): void => {
        // pinned: analytics event name, renaming it breaks dashboards
        posthog.capture('replay_vision_home_view_selected', { view_kind: kind, in_overflow: inOverflow })
        setView(next)
    }
    const item = (key: VisionHomeView, label: React.ReactNode, icon: JSX.Element): JSX.Element => (
        <LemonButton
            size="small"
            icon={icon}
            active={view === key}
            aria-current={view === key ? 'page' : undefined}
            onClick={() => select(key, key)}
            data-attr={`vision-home-menu-${key}`}
            data-home-menu-item=""
        >
            {label}
        </LemonButton>
    )

    // On a narrow bar these keep only their icons, so the scanner tabs keep their room.
    const iconOnNarrowBar = (key: VisionHomeView, label: string, icon: JSX.Element): JSX.Element => (
        <LemonButton
            size="small"
            icon={icon}
            active={view === key}
            aria-current={view === key ? 'page' : undefined}
            aria-label={label}
            tooltip={label}
            onClick={() => select(key, key)}
            data-attr={`vision-home-menu-${key}`}
            data-home-menu-item=""
        >
            <span className="hidden @[60rem]:inline">{label}</span>
        </LemonButton>
    )

    const tabCount = Math.min(MAX_SCANNER_TABS, pickerScanners.length)
    const newScannerItem = {
        label: 'New scanner',
        icon: <IconPlus />,
        to: urls.replayVisionNewScanner(),
        'data-attr': 'vision-home-menu-new-scanner',
    }
    const scannerItems = (scanners: ReplayScanner[]): LemonMenuItem[] =>
        scanners.map((scanner) => {
            const status = scannerStatuses[scanner.id]
            return {
                label: (
                    <span className="flex w-full items-center gap-2">
                        <StatusDot status={status} />
                        <span className="flex-1">{scanner.name || 'Untitled scanner'}</span>
                        {status && isProblemStatus(status) ? (
                            // The row's own dot already shows the tone, so the label drops its dot.
                            <ScannerStatusLabel
                                status={status}
                                className="text-xs text-secondary [&>span:first-child]:hidden"
                            />
                        ) : (
                            <Count value={highlightCounts?.byScanner[scanner.id]} title={COUNT_TITLE} />
                        )}
                    </span>
                ),
                active: scanner.id === view,
                onClick: () => select(scanner.id, 'scanner', true),
                'data-attr': 'vision-home-menu-scanner',
            }
        })

    // One More menu per number of visible tabs, so its list holds exactly the scanners without a tab.
    const fewestTabs = Math.min(MIN_SCANNER_TABS, tabCount)
    const moreMenus = Array.from({ length: tabCount + 1 - fewestTabs }, (_, offset) => {
        const shown = fewestTabs + offset
        const rest = pickerScanners.slice(shown)
        const selectedInRest = rest.find((scanner) => scanner.id === view)
        const visibility = shown === tabCount ? MORE_SHOWN_FROM[shown] : MORE_SHOWN_UNTIL_NEXT[shown]
        if (rest.length === 0) {
            return (
                <div key={shown} className={visibility}>
                    <LemonButton
                        size="small"
                        icon={<IconPlus />}
                        to={urls.replayVisionNewScanner()}
                        tooltip="New scanner"
                        data-attr="vision-home-menu-new-scanner"
                        data-home-menu-item=""
                    />
                </div>
            )
        }
        return (
            <div key={shown} className={visibility}>
                <LemonMenu
                    items={[
                        {
                            items: scannerItems(rest),
                        },
                        { items: [newScannerItem] },
                    ]}
                >
                    <LemonButton
                        size="small"
                        active={!!selectedInRest}
                        sideIcon={<IconChevronDown />}
                        aria-current={selectedInRest ? 'page' : undefined}
                        data-attr="vision-home-menu-scanner-picker"
                        data-home-menu-item=""
                    >
                        <span className="flex items-center gap-2 whitespace-nowrap">
                            {selectedInRest ? (
                                <>
                                    <StatusDot status={scannerStatuses[selectedInRest.id]} />
                                    <span className="max-w-28 truncate">
                                        {selectedInRest.name || 'Untitled scanner'}
                                    </span>
                                    <Count value={highlightCounts?.byScanner[selectedInRest.id]} title={COUNT_TITLE} />
                                </>
                            ) : (
                                <>
                                    <span className="text-secondary">More</span>
                                    <span className="text-xs text-secondary">{rest.length}</span>
                                </>
                            )}
                        </span>
                    </LemonButton>
                </LemonMenu>
            </div>
        )
    })

    return (
        <div className="@container">
            <nav className="flex items-center gap-1 border-b pb-2" aria-label="Replay vision" onKeyDown={moveFocus}>
                {item(
                    'all',
                    <span className="flex items-center gap-1.5">
                        All highlights <Count value={highlightCounts?.total} title={COUNT_TITLE} />
                    </span>,
                    <IconSparkles />
                )}
                {/* A fieldset, so its legend sits on the outline's top edge as the group's label. */}
                <fieldset className="ml-1 flex items-center gap-1 rounded border px-1 pb-0.5">
                    <legend className="ml-1.5 px-1 text-xxs leading-none font-semibold text-secondary">Scanners</legend>
                    {pickerScanners.slice(0, tabCount).map((scanner, index) => (
                        <div key={scanner.id} className={TAB_SHOWN[index]}>
                            <LemonButton
                                size="small"
                                active={view === scanner.id}
                                aria-current={view === scanner.id ? 'page' : undefined}
                                onClick={() => select(scanner.id, 'scanner')}
                                data-attr="vision-home-menu-scanner-tab"
                                data-home-menu-item=""
                            >
                                <span className="flex items-center gap-2 whitespace-nowrap">
                                    <StatusDot status={scannerStatuses[scanner.id]} />
                                    <span className="max-w-28 truncate @[60rem]:max-w-40">
                                        {scanner.name || 'Untitled scanner'}
                                    </span>
                                    <Count value={highlightCounts?.byScanner[scanner.id]} title={COUNT_TITLE} />
                                </span>
                            </LemonButton>
                        </div>
                    ))}
                    {moreMenus}
                </fieldset>
                <div className="ml-auto flex items-center gap-1">
                    {iconOnNarrowBar('search', 'Search sessions', <IconSearch />)}
                    {iconOnNarrowBar('usage', 'Usage', <IconPiggyBank />)}
                </div>
            </nav>
        </div>
    )
}
