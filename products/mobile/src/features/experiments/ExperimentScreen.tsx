import * as Clipboard from 'expo-clipboard'
import { useRouter } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Linking, RefreshControl, ScrollView, Text, View } from 'react-native'

import { ApiError } from '@/api/client'
import type { ExperimentApi } from '@/api/experiments'
import { useAuthStore } from '@/auth/authStore'
import { useViewer } from '@/auth/useViewer'
import { EXPERIMENT_OBJECT_TYPE } from '@/features/chat/objectContext'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { ViewChrome } from '@/features/views/screen/ViewChrome'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { safeHttpsUrl } from '@/lib/urls'
import { useClockPreference } from '@/lib/useClockPreference'
import { useNow } from '@/lib/useNow'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { ChevronUpIcon } from '@/ui/icons/ChevronUpIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'

import { AboutNumberSheet } from './AboutNumberSheet'
import { type AboutCopy, type AboutWhat, metricAboutCopy, targetAboutCopy } from './aboutCopy'
import { useExperimentActions } from './actionHooks'
import { type ExperimentOpenSource, trackExperimentOpened } from './analytics'
import { ConclusionCard } from './ConclusionCard'
import { DetailSection } from './DetailSection'
import { DraftSections } from './DraftSections'
import {
    trackExperimentChatOpened,
    trackExperimentHypothesisToggled,
    trackExperimentLinkCopied,
    trackExperimentNumberExplained,
    trackExperimentOpenedInWeb,
} from './detailAnalytics'
import {
    exposuresAsOf,
    useExposures,
    useHealth,
    useRecalculation,
    useRunningTimeTarget,
    useScreenActive,
    useWatching,
} from './detailHooks'
import {
    audienceOf,
    bylineOf,
    conclusionOf,
    draftVariantsOf,
    exposureModelOf,
    exposureTotalOf,
    formatCount,
    healthItemsOf,
    isWatching,
    type MetricCardModel,
    metricCardOf,
    metricDefsOf,
    progressOf,
    rolloutOf,
    statsSettingsOf,
    statusCardOf,
} from './detailModel'
import { ExperimentActionBar, PendingApprovalBanner } from './ExperimentActionBar'
import { ExperimentHeader } from './ExperimentHeader'
import { ExperimentSkeleton } from './ExperimentSkeleton'
import { ExposuresCard } from './ExposuresCard'
import { experimentMenuItems } from './experimentMenu'
import {
    type ExperimentStatus,
    experimentStatusOf,
    freshnessOf,
    headlineOf,
    isLiveStatus,
    variantKeysOf,
    webExperimentUrl,
    webFlagUrl,
} from './experimentModel'
import { HealthCard } from './HealthCard'
import { HypothesisCard } from './HypothesisCard'
import { markHeadlineSeen, useExperiment, useExperimentsContext, useLatestResults } from './hooks'
import { MetricCard } from './MetricCard'
import { ProgressCard } from './ProgressCard'
import { ResultsStatusCard } from './ResultsStatusCard'
import { OpenOnWebRow, RolloutRow } from './RolloutRow'
import { WatchingCard } from './WatchingCard'

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/** Experiment ids are integers. Anything else cannot be one, so the screen says so without a request. */
function isExperimentId(id: string): boolean {
    return /^\d+$/.test(id)
}

interface ExperimentScreenProps {
    experimentId: string
    from?: ExperimentOpenSource
}

export function ExperimentScreen({ experimentId, from = 'other' }: ExperimentScreenProps): ReactElement {
    const styles = useStyles()
    return (
        <OverlayHost>
            <View style={styles.screen} testID="experiment-screen">
                <ExperimentGate experimentId={experimentId} from={from} />
            </View>
        </OverlayHost>
    )
}

function Placeholder({ children, onBack }: { children: ReactElement; onBack: () => void }): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    return (
        <>
            <View style={[styles.fill, styles.placeholder, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}>
                {children}
            </View>
            <ViewChrome onBack={onBack} />
        </>
    )
}

function ExperimentGate({ experimentId, from }: { experimentId: string; from: ExperimentOpenSource }): ReactElement {
    const colors = useColors()
    const { mode, access } = useExperimentsContext()
    const goBack = useViewBack()
    if (mode === 'live' && access.state !== 'ok') {
        return (
            <Placeholder onBack={goBack}>
                <ViewsReauthState access={access} feature="experiments" />
            </Placeholder>
        )
    }
    if (mode === 'loading') {
        return (
            <Placeholder onBack={goBack}>
                <ExperimentSkeleton />
            </Placeholder>
        )
    }
    if (!isExperimentId(experimentId)) {
        return (
            <Placeholder onBack={goBack}>
                <StateView
                    icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                    title="Couldn't find this experiment"
                    message="This link doesn't point to an experiment. Go back and open it from the experiments list."
                    actionLabel="Go back"
                    onAction={goBack}
                    testID="experiment-not-found"
                />
            </Placeholder>
        )
    }
    return <ExperimentContent experimentId={experimentId} from={from} onBack={goBack} />
}

function ExperimentContent({
    experimentId,
    from,
    onBack,
}: {
    experimentId: string
    from: ExperimentOpenSource
    onBack: () => void
}): ReactElement {
    const colors = useColors()
    const experiment = useExperiment(experimentId)
    if (experiment.data) {
        return <ExperimentLoaded experiment={experiment.data} from={from} onBack={onBack} />
    }
    if (!experiment.isError) {
        return (
            <Placeholder onBack={onBack}>
                <ExperimentSkeleton />
            </Placeholder>
        )
    }
    const missing = experiment.error instanceof ApiError && experiment.error.status === 404
    return (
        <Placeholder onBack={onBack}>
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title={missing ? "Couldn't find this experiment" : "Couldn't load this experiment"}
                message={
                    missing
                        ? 'It may have been deleted, or it belongs to another project.'
                        : 'Check your connection and try again.'
                }
                actionLabel={missing ? 'Go back' : 'Try again'}
                onAction={missing ? onBack : () => experiment.refetch()}
                testID={missing ? 'experiment-not-found' : 'experiment-error'}
            />
        </Placeholder>
    )
}

type AboutTarget =
    | {
          kind: 'metric'
          role: 'primary' | 'secondary'
          index: number
          what: Exclude<AboutWhat, 'target'>
          variantKey: string
      }
    | { kind: 'target' }

function runningForText(experiment: ExperimentApi, now: number): string | null {
    const start = experiment.start_date ? Date.parse(experiment.start_date) : Number.NaN
    if (Number.isNaN(start)) {
        return null
    }
    const end = experiment.end_date ? Date.parse(experiment.end_date) : now
    const ms = Math.max(0, end - start)
    if (ms < HOUR_MS) {
        return `${Math.floor(ms / MINUTE_MS)} min`
    }
    if (ms < DAY_MS) {
        return `${Math.floor(ms / HOUR_MS)} h`
    }
    const days = Math.floor(ms / DAY_MS)
    return `${days} ${days === 1 ? 'day' : 'days'}`
}

function updatedText(updatedAt: number | null, now: number): string | null {
    if (updatedAt === null) {
        return null
    }
    const seconds = Math.max(0, Math.round((now - updatedAt) / 1000))
    return seconds < 60 ? `Updated ${seconds} s ago` : `Updated ${Math.floor(seconds / 60)} min ago`
}

function ExperimentLoaded({
    experiment,
    from,
    onBack,
}: {
    experiment: ExperimentApi
    from: ExperimentOpenSource
    onBack: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const viewer = useViewer()
    const viewerUuid = useAuthStore((state) => state.user?.uuid ?? null)
    const clock24 = useClockPreference()
    const { scope, dataScope } = useExperimentsContext()
    const toasts = useToasts()
    const actions = useExperimentActions()
    const active = useScreenActive()
    const id = String(experiment.id)

    const [menuOpen, setMenuOpen] = useState(false)
    const [hypothesisOpen, setHypothesisOpen] = useState(false)
    const [secondaryOpen, setSecondaryOpen] = useState(false)
    const [about, setAbout] = useState<AboutTarget | null>(null)

    const status: ExperimentStatus = experimentStatusOf(experiment)
    const live = isLiveStatus(status)
    const started = Boolean(experiment.start_date) && status !== 'draft'
    const latest = useLatestResults(id)
    const latestData = latest.data
    const watchingNow = isWatching(experiment, status, Date.now())
    const target = useRunningTimeTarget(experiment, live && started)
    const health = useHealth(experiment, live && started)
    const exposures = useExposures(experiment, {
        enabled: started,
        watching: watchingNow,
        active,
        asOf: exposuresAsOf(latestData, latest.isError, watchingNow),
    })
    const watch = useWatching(experiment, exposures, { watching: watchingNow, active })
    const showToast = toasts.show
    const recalculation = useRecalculation(experiment, latestData, status, showToast)
    const now = useNow(recalculation.phase.kind === 'window' || watchingNow ? 1000 : 30_000)
    const nowMs = now.getTime()
    const watching = isWatching(experiment, status, nowMs)

    const settings = useMemo(() => statsSettingsOf(experiment, latestData), [experiment, latestData])
    const variantOrder = useMemo(() => variantKeysOf(experiment), [experiment])
    const defs = useMemo(() => metricDefsOf(experiment), [experiment])
    const primaryCards = useMemo(
        () => defs.primary.map((def) => metricCardOf(def, latestData, variantOrder)),
        [defs, latestData, variantOrder]
    )
    const secondaryCards = useMemo(
        () => defs.secondary.map((def) => metricCardOf(def, latestData, variantOrder)),
        [defs, latestData, variantOrder]
    )
    const exposureModel = useMemo(
        () => exposureModelOf(exposures.query.data, variantOrder),
        [exposures.query.data, variantOrder]
    )
    const healthItems = useMemo(
        () => healthItemsOf(health.data, exposures.query.data),
        [health.data, exposures.query.data]
    )
    const progress = progressOf(target.data, exposureTotalOf(exposures.query.data))
    const rollout = rolloutOf(experiment, status)
    const byline = bylineOf(experiment, status, settings, { now, viewerUuid, clock24 })
    const statusCard = statusCardOf({
        status,
        latest: latestData,
        latestFailed: latest.isError,
        phase: recalculation.phase,
        mine: latestData?.id !== undefined && latestData.id === recalculation.mineRunId,
        now: nowMs,
        clock24,
    })

    // Sent once per visit, with the state the screen first showed.
    const opened = useRef(false)
    useEffect(() => {
        if (!opened.current && (latestData !== undefined || latest.isError)) {
            opened.current = true
            trackExperimentOpened({
                source: from,
                status,
                hasResult: primaryCards.some((card) => card.state === 'ready'),
            })
        }
    }, [from, status, latestData, latest.isError, primaryCards])
    // The list's "changed" dot goes out once the person has seen the headline here.
    useEffect(() => {
        if (latestData !== undefined) {
            markHeadlineSeen(dataScope, id, headlineOf(experiment, latestData))
        }
    }, [dataScope, id, experiment, latestData])

    const webUrl = scope ? safeHttpsUrl(webExperimentUrl(scope.host, scope.projectId, id)) : undefined
    const flagUrl =
        scope && rollout.flagId !== null
            ? safeHttpsUrl(webFlagUrl(scope.host, scope.projectId, rollout.flagId))
            : undefined
    const openWeb = webUrl
        ? (): void => {
              trackExperimentOpenedInWeb({ target: 'experiment' })
              Linking.openURL(webUrl).catch(() => undefined)
          }
        : undefined
    const openFlag = flagUrl
        ? (): void => {
              trackExperimentOpenedInWeb({ target: 'flag' })
              Linking.openURL(flagUrl).catch(() => undefined)
          }
        : undefined
    const copyLink = webUrl
        ? (): void => {
              Clipboard.setStringAsync(webUrl)
                  .then(() => {
                      trackExperimentLinkCopied()
                      showToast('Link copied')
                  })
                  .catch(() => showToast("Couldn't copy the link"))
          }
        : undefined
    const title = experiment.name.trim() || 'Untitled experiment'
    const openChat = useCallback((): void => {
        trackExperimentChatOpened()
        router.push({
            pathname: '/chat',
            params: { entry: 'experiment', objectType: EXPERIMENT_OBJECT_TYPE, objectId: id, objectLabel: title },
        })
    }, [router, id, title])

    const explain = (target: AboutTarget): void => {
        trackExperimentNumberExplained({ what: target.kind === 'target' ? 'target' : target.what })
        setAbout(target)
    }
    const cardsFor = (role: 'primary' | 'secondary'): MetricCardModel[] =>
        role === 'primary' ? primaryCards : secondaryCards
    let aboutCopy: AboutCopy | null = null
    if (about?.kind === 'target') {
        aboutCopy = progress
            ? targetAboutCopy({ progress, name: title, runningFor: runningForText(experiment, nowMs) })
            : null
    } else if (about) {
        const card = cardsFor(about.role)[about.index]
        aboutCopy = card
            ? metricAboutCopy({
                  what: about.what,
                  card,
                  variantKey: about.variantKey,
                  settings,
                  runAt: freshnessOf(latestData, nowMs).resultsAt,
                  clock24,
              })
            : null
    }
    // The sheet keeps its last text while it slides away.
    const lastAbout = useRef<AboutCopy | null>(null)
    if (aboutCopy) {
        lastAbout.current = aboutCopy
    }

    const scrollTitle = useScrollTitle(title)
    const menuItems = experimentMenuItems(experiment, {
        onOpenSheet: actions.open,
        onOpenWeb: openWeb,
        onCopyLink: copyLink,
        onOpenFlag: openFlag,
    })

    const metricSection = (role: 'primary' | 'secondary', cards: MetricCardModel[]): ReactElement[] =>
        cards.map((card, index) => (
            <MetricCard
                key={card.def.uuid ?? `${role}-${index}`}
                card={card}
                settings={settings}
                onExplain={(what, variantKey) =>
                    explain({ kind: 'metric', role, index, what: what === 'target' ? 'value' : what, variantKey })
                }
                testID={`experiment-${role}-metric-${index}`}
            />
        ))

    const primarySection =
        primaryCards.length > 0 ? (
            <DetailSection title={primaryCards.length > 1 ? 'Primary metrics' : 'Primary metric'}>
                {metricSection('primary', primaryCards)}
            </DetailSection>
        ) : (
            <DetailSection title="Primary metric">
                <View style={styles.note}>
                    <Text style={styles.noteText}>No primary metric. Add one on the web to see results here.</Text>
                </View>
            </DetailSection>
        )

    const exposureSection = started ? (
        <DetailSection
            title="Exposures"
            aside={exposureModel ? `${formatCount(exposureModel.total)} total` : null}
            testID="experiment-exposures-section"
        >
            {exposureModel ? (
                <ExposuresCard model={exposureModel} />
            ) : (
                <View style={styles.note}>
                    <Text style={styles.noteText}>
                        {exposures.query.isError
                            ? "Couldn't load the exposures. Pull down to try again."
                            : 'Loading the exposures…'}
                    </Text>
                </View>
            )}
        </DetailSection>
    ) : null

    const progressSection =
        live && started && (progress || target.isLoading) ? (
            <DetailSection title="Progress">
                {progress ? (
                    <ProgressCard progress={progress} onPress={() => explain({ kind: 'target' })} />
                ) : (
                    <View style={styles.note}>
                        <Text style={styles.noteText}>Loading the target…</Text>
                    </View>
                )}
            </DetailSection>
        ) : null

    const flagSection = (
        <DetailSection title="Feature flag">
            <RolloutRow model={rollout} onOpenFlag={openFlag} />
        </DetailSection>
    )

    let body: ReactElement
    if (status === 'draft') {
        body = (
            <>
                <DraftSections
                    primary={defs.primary}
                    secondary={defs.secondary}
                    variants={draftVariantsOf(experiment)}
                    audience={audienceOf(experiment)}
                />
                {flagSection}
                <View style={styles.webRow}>
                    <OpenOnWebRow title="Edit on the web" sub="Metrics, variants and audience" onPress={openWeb} />
                </View>
            </>
        )
    } else if (status === 'complete') {
        body = (
            <>
                <ConclusionCard model={conclusionOf(experiment)} />
                {statusCard ? <ResultsStatusCard model={statusCard} /> : null}
                {primarySection}
                {exposureSection}
                {flagSection}
                <View style={styles.webRow}>
                    <OpenOnWebRow
                        title="Open on the web"
                        sub="Variants, recordings and daily charts"
                        onPress={openWeb}
                    />
                </View>
            </>
        )
    } else {
        body = (
            <>
                {watching ? (
                    <WatchingCard
                        total={exposureTotalOf(exposures.query.data)}
                        history={watch.history}
                        updated={updatedText(exposures.updatedAt, nowMs)}
                        live={watch.live}
                    />
                ) : null}
                {statusCard ? <ResultsStatusCard model={statusCard} /> : null}
                {progressSection}
                {primarySection}
                {secondaryCards.length > 0 ? (
                    <View style={styles.secondary}>
                        <Pressable44
                            onPress={() => setSecondaryOpen((open) => !open)}
                            accessibilityRole="button"
                            accessibilityLabel={`Secondary metrics, ${secondaryCards.length}`}
                            accessibilityState={{ expanded: secondaryOpen }}
                            pressedBackground={colors.pressed}
                            style={styles.secondaryButton}
                            testID="experiment-secondary-toggle"
                        >
                            <Text style={styles.secondaryText}>
                                Secondary metrics <Text style={styles.secondaryCount}>({secondaryCards.length})</Text>
                            </Text>
                            {secondaryOpen ? (
                                <ChevronUpIcon size={18} color={colors.secondary} />
                            ) : (
                                <ChevronDownIcon size={18} color={colors.secondary} />
                            )}
                        </Pressable44>
                        {secondaryOpen ? (
                            <View style={styles.secondaryCards}>{metricSection('secondary', secondaryCards)}</View>
                        ) : null}
                    </View>
                ) : null}
                {exposureSection}
                {healthItems.length > 0 ? (
                    <DetailSection title="Health">
                        <HealthCard items={healthItems} />
                    </DetailSection>
                ) : null}
                {flagSection}
                {watching ? null : (
                    <View style={styles.webRow}>
                        <OpenOnWebRow
                            title="Open on the web"
                            sub="Variants, recordings and daily charts"
                            onPress={openWeb}
                        />
                    </View>
                )}
            </>
        )
    }

    return (
        <>
            <ScrollView
                style={styles.fill}
                contentContainerStyle={[styles.content, { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP) }]}
                refreshControl={
                    <RefreshControl
                        refreshing={recalculation.pulling}
                        onRefresh={recalculation.onPull}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={topOffset(insets, SCREEN_CONTENT_TOP)}
                    />
                }
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                testID="experiment-scroll"
            >
                <ExperimentHeader
                    onTitleLayout={scrollTitle.onTitleLayout}
                    eyebrow={viewer.projectName ? `Experiment · ${viewer.projectName}` : 'Experiment'}
                    status={status}
                    name={title}
                    byline={byline}
                />
                {experiment.description?.trim() ? (
                    <HypothesisCard
                        text={experiment.description.trim()}
                        expanded={hypothesisOpen}
                        onToggle={() => {
                            trackExperimentHypothesisToggled({ expanded: !hypothesisOpen })
                            setHypothesisOpen(!hypothesisOpen)
                        }}
                    />
                ) : null}
                {live ? <PendingApprovalBanner experiment={experiment} /> : null}
                {body}
            </ScrollView>
            <ViewChrome title={scrollTitle.title} onBack={onBack} onMore={() => setMenuOpen(true)} />
            <ExperimentActionBar
                experiment={experiment}
                latest={latestData ?? null}
                actions={actions}
                onChat={openChat}
                onToast={showToast}
            />
            <HeaderMenu
                visible={menuOpen}
                onClose={() => setMenuOpen(false)}
                items={menuItems}
                testID="experiment-menu"
            />
            <AboutNumberSheet
                visible={aboutCopy !== null}
                copy={aboutCopy ?? lastAbout.current}
                onClose={() => setAbout(null)}
            />
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    fill: {
        flex: 1,
    },
    placeholder: {
        paddingHorizontal: layout.detailGutter,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
        paddingBottom: 28,
    },
    note: {
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    noteText: {
        ...type.metaSmall,
        color: colors.secondary,
    },
    secondary: {
        marginTop: 12,
    },
    secondaryButton: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        minHeight: 52,
        paddingHorizontal: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    secondaryText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    secondaryCount: {
        fontWeight: '400',
        color: colors.secondary,
    },
    secondaryCards: {
        marginTop: 10,
        gap: 10,
    },
    webRow: {
        marginTop: 10,
    },
}))
