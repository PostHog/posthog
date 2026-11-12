import type { ReactElement, ReactNode } from 'react'
import { ActivityIndicator, Text, TextInput, View } from 'react-native'

import type { ExperimentConclusionApi } from '@/api/experiments'
import { formatClock } from '@/lib/dates'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { InfoIcon } from '@/ui/icons/InfoIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { fonts, iconSizes, inputReset, radii, type } from '@/ui/tokens'

import { CONCLUSION_COPY, CONCLUSIONS, conclusionColor } from './conclusionCopy'
import { COMMENT_MAX_LENGTH, type CodeLine } from './finishModel'

// The parts the experiment action sheets share: the finish, launch, pause, resume, archive and edit conclusion sheets.

/** Inline code, such as a flag key or a variant, inside a `Text`. */
export function Code({ children }: { children: ReactNode }): ReactElement {
    const styles = useStyles()
    return <Text style={styles.code}>{children}</Text>
}

export function SheetTitle({ children }: { children: string }): ReactElement {
    const styles = useStyles()
    return (
        <Text style={styles.title} accessibilityRole="header">
            {children}
        </Text>
    )
}

export function SheetDescription({ line, children }: { line?: CodeLine; children?: ReactNode }): ReactElement {
    const styles = useStyles()
    return (
        <Text style={styles.description}>
            {line ? (
                <>
                    {line.before}
                    {line.code ? <Code>{line.code}</Code> : null}
                    {line.after}
                </>
            ) : (
                children
            )}
        </Text>
    )
}

export function SheetError({ message, testID }: { message: string | null; testID: string }): ReactElement | null {
    const styles = useStyles()
    if (!message) {
        return null
    }
    return (
        <Text style={styles.error} accessibilityRole="alert" testID={testID}>
            {message}
        </Text>
    )
}

export function FieldLabel({ label, optional = false }: { label: string; optional?: boolean }): ReactElement {
    const styles = useStyles()
    return (
        <Text style={styles.fieldLabel}>
            {label}
            {optional ? <Text style={styles.optional}> (optional)</Text> : null}
        </Text>
    )
}

export function FieldHelp({ children }: { children: ReactNode }): ReactElement {
    const styles = useStyles()
    return <Text style={styles.help}>{children}</Text>
}

export function Tag({ label, tone }: { label: string; tone: 'good' | 'quiet' }): ReactElement {
    const styles = useStyles()
    return (
        <View style={[styles.tag, tone === 'good' ? styles.tagGood : styles.tagQuiet]}>
            <Text style={[styles.tagText, tone === 'good' ? styles.tagTextGood : styles.tagTextQuiet]}>{label}</Text>
        </View>
    )
}

interface RadioCardProps {
    selected: boolean
    onPress: () => void
    title: ReactNode
    meta?: string | null
    disabled?: boolean
    accessibilityLabel: string
    testID: string
}

/** A whole-row radio option with a title line and an optional meta line, as in the web's release mode cards. */
export function RadioCard({
    selected,
    onPress,
    title,
    meta,
    disabled = false,
    accessibilityLabel,
    testID,
}: RadioCardProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="radio"
            accessibilityLabel={accessibilityLabel}
            accessibilityState={{ checked: selected, disabled }}
            pressedBackground={colors.pressed}
            style={[styles.card, selected && styles.cardSelected]}
            testID={testID}
        >
            <View style={[styles.radio, selected && styles.radioSelected]}>
                {selected ? <View style={styles.radioDot} /> : null}
            </View>
            <View style={styles.cardBody}>
                <View style={styles.cardTitle}>{title}</View>
                {meta ? <Text style={styles.cardMeta}>{meta}</Text> : null}
            </View>
        </Pressable44>
    )
}

/** A radio title that is plain text. */
export function CardTitleText({ children, mono = false }: { children: ReactNode; mono?: boolean }): ReactElement {
    const styles = useStyles()
    return <Text style={[styles.cardTitleText, mono && styles.cardTitleMono]}>{children}</Text>
}

interface CheckCardProps {
    checked: boolean
    onPress: () => void
    disabled?: boolean
    /** A borderless row, for a secondary option under a group. */
    plain?: boolean
    accessibilityLabel: string
    testID: string
    children: ReactNode
}

export function CheckCard({
    checked,
    onPress,
    disabled = false,
    plain = false,
    accessibilityLabel,
    testID,
    children,
}: CheckCardProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="checkbox"
            accessibilityLabel={accessibilityLabel}
            accessibilityState={{ checked, disabled }}
            pressedBackground={colors.pressed}
            style={[
                styles.check,
                plain && styles.checkPlain,
                checked && !disabled && !plain && styles.checkSelected,
                disabled && styles.checkDisabled,
            ]}
            testID={testID}
        >
            <View
                style={[
                    styles.box,
                    checked && !disabled && styles.boxChecked,
                    disabled && { borderColor: colors.disabled },
                ]}
            >
                {checked && !disabled ? <CheckIcon size={14} color={colors.onInk} strokeWidth={3} /> : null}
            </View>
            <Text style={[styles.checkText, plain && styles.checkTextPlain, disabled && styles.checkTextDisabled]}>
                {children}
            </Text>
        </Pressable44>
    )
}

export function InfoBanner({ children, testID }: { children: ReactNode; testID?: string }): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <View style={styles.banner} testID={testID}>
            <InfoIcon size={18} color={colors.blue} />
            <Text style={styles.bannerText}>{children}</Text>
        </View>
    )
}

export function SheetNote({
    icon,
    children,
    testID,
}: {
    icon: 'info' | 'spinner' | 'none'
    children: ReactNode
    testID?: string
}): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <View style={styles.note} testID={testID}>
            {icon === 'info' ? <InfoIcon size={iconSizes.inline} color={colors.secondary} /> : null}
            {icon === 'spinner' ? <ActivityIndicator size="small" color={colors.secondary} /> : null}
            <Text style={styles.noteText}>{children}</Text>
        </View>
    )
}

interface ConclusionRadiosProps {
    value: ExperimentConclusionApi | null
    /** Tagged "Suggested by the results". */
    suggested: ExperimentConclusionApi | null
    onChange: (conclusion: ExperimentConclusionApi) => void
    disabled: boolean
    testID: string
}

export function ConclusionRadios({
    value,
    suggested,
    onChange,
    disabled,
    testID,
}: ConclusionRadiosProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <View style={styles.group} accessibilityRole="radiogroup" accessibilityLabel="Conclusion">
            {CONCLUSIONS.map((conclusion) => {
                const copy = CONCLUSION_COPY[conclusion]
                return (
                    <RadioCard
                        key={conclusion}
                        selected={value === conclusion}
                        onPress={() => onChange(conclusion)}
                        disabled={disabled}
                        accessibilityLabel={
                            conclusion === suggested ? `${copy.label}, suggested by the results` : copy.label
                        }
                        title={
                            <>
                                <View style={[styles.dot, { backgroundColor: conclusionColor(conclusion, colors) }]} />
                                <CardTitleText>{copy.label}</CardTitleText>
                                {conclusion === suggested ? (
                                    <Tag label="Suggested by the results" tone="quiet" />
                                ) : null}
                            </>
                        }
                        meta={copy.description}
                        testID={`${testID}-${conclusion}`}
                    />
                )
            })}
        </View>
    )
}

interface CommentFieldProps {
    value: string
    onChange: (value: string) => void
    editable: boolean
    onFocus?: () => void
    testID: string
}

export function CommentField({ value, onChange, editable, onFocus, testID }: CommentFieldProps): ReactElement {
    const { colors, scheme } = useTheme()
    const styles = useStyles()
    return (
        <TextInput
            value={value}
            onChangeText={onChange}
            onFocus={onFocus}
            editable={editable}
            multiline
            disableFullscreenUI
            maxLength={COMMENT_MAX_LENGTH}
            placeholder="Optional details about why this conclusion was selected"
            placeholderTextColor={colors.tertiary}
            keyboardAppearance={scheme}
            textAlignVertical="top"
            style={styles.comment}
            accessibilityLabel="Comment"
            testID={testID}
        />
    )
}

export type PrimaryTone = 'ink' | 'accent' | 'danger'

interface SheetButtonProps {
    label: string
    onPress: () => void
    disabled?: boolean
    pending?: boolean
    tone: PrimaryTone | 'ghost'
    icon?: ReactNode
    testID: string
}

export function SheetButton({
    label,
    onPress,
    disabled = false,
    pending = false,
    tone,
    icon,
    testID,
}: SheetButtonProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    const fill =
        tone === 'ghost'
            ? undefined
            : tone === 'accent'
              ? colors.accent
              : tone === 'danger'
                ? colors.orange
                : colors.ink
    const pressed =
        tone === 'ghost'
            ? colors.pressed
            : tone === 'accent' || tone === 'danger'
              ? colors.accentHover
              : colors.inkHover
    const textColor = tone === 'ghost' ? colors.ink : tone === 'ink' ? colors.onInk : colors.onAccent
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled || pending}
            accessibilityRole="button"
            accessibilityLabel={label}
            accessibilityState={{ disabled: disabled || pending, busy: pending }}
            pressedBackground={pressed}
            style={[
                styles.button,
                tone === 'ghost' ? styles.ghost : { backgroundColor: fill },
                (disabled || pending) && tone !== 'ghost' && styles.buttonDimmed,
            ]}
            testID={testID}
        >
            {pending ? <ActivityIndicator size="small" color={textColor} /> : icon}
            <Text style={[styles.buttonText, { color: textColor }]} numberOfLines={1}>
                {label}
            </Text>
        </Pressable44>
    )
}

interface SheetFooterProps {
    /** Why the primary button is disabled, above the buttons, as the web's `disabledReason` tooltip says it. */
    reason: string | null
    pending: boolean
    onCancel: () => void
    primary: Omit<SheetButtonProps, 'pending' | 'disabled'>
}

/** Cancel and one primary button, pinned under the sheet's scrolling body. */
export function SheetFooter({ reason, pending, onCancel, primary }: SheetFooterProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <View style={styles.footer}>
            {reason ? (
                <View style={styles.reason} testID={`${primary.testID}-reason`}>
                    <InfoIcon size={iconSizes.inline} color={colors.secondary} />
                    <Text style={styles.reasonText}>{reason}</Text>
                </View>
            ) : null}
            <View style={styles.footerRow}>
                <Pressable44
                    onPress={onCancel}
                    disabled={pending}
                    accessibilityRole="button"
                    accessibilityLabel="Cancel"
                    accessibilityState={{ disabled: pending }}
                    pressedBackground={colors.pressed}
                    style={[styles.button, styles.ghost, styles.cancel]}
                    testID={`${primary.testID}-cancel`}
                >
                    <Text style={[styles.buttonText, { color: pending ? colors.disabled : colors.ink }]}>Cancel</Text>
                </Pressable44>
                <View style={styles.primary}>
                    <SheetButton {...primary} disabled={reason !== null} pending={pending} />
                </View>
            </View>
        </View>
    )
}

interface ApprovalNoticeProps {
    /** `change_request_pending`: the server sent nothing new, because a request already waited. */
    alreadyPending: boolean
    /** Epoch ms of the 409. */
    at: number
    onDone: () => void
    onOpenApproval?: () => void
    testID: string
    children: ReactNode
}

/** What a sheet shows after a 409 from the flag's approval gate: a change request waits, and nothing changed. */
export function ApprovalNotice({
    alreadyPending,
    at,
    onDone,
    onOpenApproval,
    testID,
    children,
}: ApprovalNoticeProps): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    return (
        <View testID={testID}>
            <View style={styles.approval}>
                <View style={styles.approvalIcon}>
                    <ClockIcon size={26} color={colors.blue} />
                </View>
                <Text style={styles.approvalTitle} accessibilityRole="header">
                    Needs approval
                </Text>
                <Text style={styles.approvalText}>{children}</Text>
                <View style={styles.chip}>
                    <CheckIcon size={14} color={colors.muted} strokeWidth={2.6} />
                    <Text style={styles.chipText}>
                        {alreadyPending ? 'Request already waiting' : 'Request sent'} · {formatClock(new Date(at))}
                    </Text>
                </View>
            </View>
            <View style={styles.approvalButtons}>
                <SheetButton label="Done" onPress={onDone} tone="ink" testID={`${testID}-done`} />
                {onOpenApproval ? (
                    <SheetButton
                        label="Open request on the web"
                        onPress={onOpenApproval}
                        tone="ghost"
                        icon={<ExternalLinkIcon size={iconSizes.inline} />}
                        testID={`${testID}-web`}
                    />
                ) : null}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    code: {
        fontFamily: fonts.mono,
        fontSize: 14,
        color: colors.ink,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        marginTop: 18,
        paddingHorizontal: 4,
    },
    description: {
        ...type.bodySmall,
        color: colors.muted,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 10,
        paddingHorizontal: 4,
    },
    fieldLabel: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.muted,
        marginTop: 20,
        marginBottom: 8,
        paddingHorizontal: 4,
    },
    optional: {
        fontWeight: '400',
        color: colors.secondary,
    },
    help: {
        ...type.meta,
        color: colors.secondary,
        marginTop: -2,
        marginBottom: 10,
        paddingHorizontal: 4,
    },
    group: {
        gap: 6,
    },
    card: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 56,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.background,
    },
    cardSelected: {
        borderWidth: 2,
        borderColor: colors.ink,
        paddingVertical: 7,
        paddingHorizontal: 11,
    },
    radio: {
        width: 22,
        height: 22,
        borderRadius: 11,
        borderWidth: 2,
        borderColor: colors.control,
        alignItems: 'center',
        justifyContent: 'center',
    },
    radioSelected: {
        borderColor: colors.ink,
    },
    radioDot: {
        width: 10,
        height: 10,
        borderRadius: 5,
        backgroundColor: colors.ink,
    },
    cardBody: {
        flex: 1,
        minWidth: 0,
    },
    cardTitle: {
        flexDirection: 'row',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 8,
    },
    cardTitleText: {
        ...type.rowTitle,
        color: colors.ink,
        flexShrink: 1,
    },
    cardTitleMono: {
        fontFamily: fonts.mono,
        fontSize: 14,
        fontWeight: '500',
    },
    cardMeta: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 2,
    },
    dot: {
        width: 8,
        height: 8,
        borderRadius: 4,
    },
    tag: {
        height: 20,
        paddingHorizontal: 7,
        borderRadius: radii.pill,
        borderWidth: 1,
        justifyContent: 'center',
    },
    tagGood: {
        borderColor: colors.diffGreenBorder,
    },
    tagQuiet: {
        borderColor: colors.border,
    },
    tagText: {
        fontSize: 12,
        fontWeight: '600',
    },
    tagTextGood: {
        color: colors.diffGreen,
    },
    tagTextQuiet: {
        color: colors.secondary,
    },
    check: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 12,
        minHeight: 56,
        paddingVertical: 15,
        paddingHorizontal: 12,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.background,
    },
    checkSelected: {
        borderWidth: 2,
        borderColor: colors.ink,
        paddingVertical: 14,
        paddingHorizontal: 11,
    },
    checkPlain: {
        minHeight: 48,
        marginTop: 6,
        paddingVertical: 13,
        borderColor: 'transparent',
        backgroundColor: 'transparent',
    },
    checkDisabled: {
        borderColor: colors.hairline,
        backgroundColor: colors.sunken,
    },
    box: {
        width: 22,
        height: 22,
        borderRadius: 6,
        borderWidth: 2,
        borderColor: colors.control,
        alignItems: 'center',
        justifyContent: 'center',
    },
    boxChecked: {
        backgroundColor: colors.ink,
        borderColor: colors.ink,
    },
    checkText: {
        ...type.bodyStrong,
        lineHeight: 21,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
    checkTextPlain: {
        ...type.bodySmall,
        fontWeight: '500',
    },
    checkTextDisabled: {
        color: colors.secondary,
    },
    banner: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
        marginTop: 16,
        paddingVertical: 12,
        paddingHorizontal: 14,
        borderRadius: radii.option,
        backgroundColor: colors.blueHighlight,
    },
    bannerText: {
        ...type.metaSmall,
        lineHeight: 20,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
    note: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
        marginTop: 10,
        paddingHorizontal: 4,
    },
    noteText: {
        ...type.metaSmall,
        color: colors.secondary,
        flex: 1,
        minWidth: 0,
    },
    comment: {
        ...inputReset,
        ...type.input,
        color: colors.ink,
        minHeight: 76,
        paddingHorizontal: 14,
        paddingTop: 12,
        paddingBottom: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.background,
    },
    footer: {
        marginTop: 18,
        marginHorizontal: -16,
        paddingTop: 12,
        paddingHorizontal: 16,
        borderTopWidth: 1,
        borderTopColor: colors.hairline,
    },
    reason: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        justifyContent: 'center',
        gap: 6,
        marginBottom: 10,
    },
    reasonText: {
        ...type.metaSmall,
        color: colors.secondary,
        textAlign: 'center',
        flexShrink: 1,
    },
    footerRow: {
        flexDirection: 'row',
        gap: 10,
    },
    primary: {
        flex: 1,
        minWidth: 0,
    },
    button: {
        height: 52,
        borderRadius: radii.pill,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        paddingHorizontal: 16,
    },
    ghost: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: 'transparent',
    },
    cancel: {
        paddingHorizontal: 22,
    },
    buttonDimmed: {
        opacity: 0.6,
    },
    buttonText: {
        ...type.button,
        flexShrink: 1,
    },
    approval: {
        alignItems: 'center',
        gap: 8,
        paddingTop: 22,
        paddingHorizontal: 8,
    },
    approvalIcon: {
        width: 52,
        height: 52,
        borderRadius: 26,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.blueHighlight,
    },
    approvalTitle: {
        ...type.sheetTitleLarge,
        color: colors.ink,
        marginTop: 6,
    },
    approvalText: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 28,
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
    },
    chipText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.muted,
        fontVariant: ['tabular-nums'],
    },
    approvalButtons: {
        marginTop: 22,
        gap: 8,
    },
}))
