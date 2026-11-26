import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, Switch, Text, TextInput, View } from 'react-native'

import { track } from '@/lib/analytics'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { inputReset, radii, type } from '@/ui/tokens'

import { openReplyUrl } from '../webLinks'
import {
    type ClassicFormAnswers,
    type ClassicFormDraft,
    type ClassicFormField,
    classicFormComplete,
    classicFormQuestions,
    combinedClassicFormAnswers,
    initialClassicFormAnswers,
    submittedClassicFormAnswers,
} from './classicForm'
import type { ClassicForm } from './classicMessages'

interface ClassicFormPanelProps {
    form: ClassicForm
    draft?: ClassicFormDraft
    onDraftChange: (draft: ClassicFormDraft) => void
    pending: boolean
    webUrl?: string
    onSubmit: (answers: ClassicFormAnswers) => Promise<boolean>
    onDismiss: () => Promise<boolean>
}

export function ClassicFormPanel({
    form,
    draft,
    onDraftChange,
    pending,
    webUrl,
    onSubmit,
    onDismiss,
}: ClassicFormPanelProps): ReactElement {
    const { colors, scheme } = useTheme()
    const styles = useStyles()
    const questions = useMemo(() => classicFormQuestions(form), [form])
    const [answers, setAnswers] = useState<ClassicFormAnswers>(() => ({
        ...initialClassicFormAnswers(questions ?? []),
        ...draft?.answers,
    }))
    const [custom, setCustom] = useState<Record<string, string>>(() => draft?.custom ?? {})
    const [skipped, setSkipped] = useState<ReadonlySet<string>>(() => new Set(draft?.skipped))
    const [busy, setBusy] = useState(false)
    const locked = useRef(false)
    const disabled = pending || busy
    const activeQuestions = questions?.filter((question) => !skipped.has(question.id)) ?? []
    const combinedAnswers = useMemo(
        () => combinedClassicFormAnswers(questions ?? [], answers, custom),
        [questions, answers, custom]
    )
    const complete = questions !== null && classicFormComplete(activeQuestions, combinedAnswers)
    useEffect(() => {
        onDraftChange({ answers, custom, skipped: [...skipped] })
    }, [answers, custom, skipped, onDraftChange])
    useEffect(() => {
        const defaults = initialClassicFormAnswers(questions ?? [])
        setAnswers((current) =>
            Object.keys(defaults).every((id) => current[id] !== undefined) ? current : { ...defaults, ...current }
        )
    }, [questions])
    useEffect(() => {
        track('mobile_decision_shown', {
            kind: 'form',
            surface: 'chat',
            agent_runtime: 'langgraph',
            question_count: form.questions.length,
        })
    }, [form.questions.length])

    const submit = async (dismiss: boolean): Promise<void> => {
        if (locked.current || disabled || (!dismiss && !complete)) return
        locked.current = true
        setBusy(true)
        onDraftChange({ answers, custom, skipped: [...skipped] })
        try {
            const accepted = dismiss
                ? await onDismiss()
                : await onSubmit(submittedClassicFormAnswers(activeQuestions, combinedAnswers))
            if (accepted)
                track('mobile_decision_answered', {
                    kind: 'form',
                    surface: 'chat',
                    agent_runtime: 'langgraph',
                    action: dismiss ? 'dismiss' : 'submit',
                    question_count: form.questions.length,
                })
        } finally {
            locked.current = false
            setBusy(false)
        }
    }
    const change = (id: string, value: string | string[]): void =>
        setAnswers((current) => ({ ...current, [id]: value }))
    const renderField = (field: ClassicFormField): ReactElement => {
        const value = answers[field.id]
        const selected = Array.isArray(value) ? value : []
        const numeric = field.type === 'number'
        return (
            <View key={field.id} style={styles.field}>
                {field.label ? (
                    <Text style={styles.label}>
                        {field.label}
                        {field.optional ? ' (optional)' : ''}
                    </Text>
                ) : null}
                {field.options.map((option) => {
                    const checked =
                        field.type === 'multi_select' ? selected.includes(option.value) : value === option.value
                    return (
                        <Pressable44
                            key={option.value}
                            accessibilityRole={field.type === 'multi_select' ? 'checkbox' : 'radio'}
                            accessibilityLabel={option.value}
                            accessibilityState={{ checked, disabled }}
                            disabled={disabled}
                            style={[styles.option, checked && styles.selected]}
                            onPress={() => {
                                if (field.type === 'multi_select')
                                    change(
                                        field.id,
                                        checked
                                            ? selected.filter((item) => item !== option.value)
                                            : [...selected, option.value]
                                    )
                                else {
                                    setCustom((current) => ({ ...current, [field.id]: '' }))
                                    change(field.id, option.value)
                                }
                            }}
                        >
                            <Text style={styles.label}>
                                {checked ? '✓ ' : ''}
                                {option.value}
                            </Text>
                            {option.description ? <Text style={styles.detail}>{option.description}</Text> : null}
                        </Pressable44>
                    )
                })}
                {field.type === 'toggle' ? (
                    <Switch
                        accessibilityLabel={field.label}
                        value={value === 'true'}
                        disabled={disabled}
                        onValueChange={(next) => change(field.id, String(next))}
                    />
                ) : field.type === 'text' || numeric || field.allowCustom ? (
                    <>
                        <TextInput
                            accessibilityLabel={
                                field.label || (field.type === 'multi_select' ? 'Other answers' : 'Your answer')
                            }
                            value={
                                field.type === 'multi_select' || field.type === 'select'
                                    ? (custom[field.id] ?? '')
                                    : typeof value === 'string'
                                      ? value
                                      : ''
                            }
                            onChangeText={(text) => {
                                if (field.type === 'multi_select') {
                                    setCustom((current) => ({ ...current, [field.id]: text }))
                                } else {
                                    if (field.type === 'select')
                                        setCustom((current) => ({ ...current, [field.id]: text }))
                                    change(field.id, text)
                                }
                            }}
                            placeholder={
                                field.placeholder ??
                                (numeric
                                    ? 'Enter a number'
                                    : field.type === 'multi_select'
                                      ? 'Other answers, one per line'
                                      : field.options.length
                                        ? 'Or type your answer'
                                        : 'Type your answer')
                            }
                            placeholderTextColor={colors.tertiary}
                            keyboardAppearance={scheme}
                            keyboardType={numeric ? 'numbers-and-punctuation' : 'default'}
                            multiline={!numeric && field.type === 'multi_select'}
                            editable={!disabled}
                            style={styles.input}
                        />
                        {numeric && (field.min !== undefined || field.max !== undefined || field.step !== undefined) ? (
                            <Text style={styles.detail}>
                                {[
                                    field.min !== undefined ? `Minimum: ${field.min}` : '',
                                    field.max !== undefined ? `Maximum: ${field.max}` : '',
                                    field.step !== undefined ? `Step: ${field.step}` : '',
                                ]
                                    .filter(Boolean)
                                    .join('. ')}
                            </Text>
                        ) : null}
                    </>
                ) : null}
            </View>
        )
    }
    return (
        <View style={styles.panel} testID="classic-form">
            <Text style={styles.label}>Needs your answer</Text>
            {questions ? (
                <ScrollView
                    style={styles.scroll}
                    contentContainerStyle={styles.questions}
                    keyboardShouldPersistTaps="handled"
                >
                    {questions.map((question) => (
                        <View key={question.id} style={styles.question}>
                            <Text style={styles.label}>{question.title}</Text>
                            <Text style={styles.body}>{question.question}</Text>
                            {!skipped.has(question.id) ? question.fields.map(renderField) : null}
                            <Pressable44
                                disabled={disabled}
                                style={[styles.textAction, disabled && styles.disabled]}
                                accessibilityLabel={`${skipped.has(question.id) ? 'Answer' : 'Skip'} question: ${question.title}`}
                                onPress={() =>
                                    setSkipped((current) => {
                                        const next = new Set(current)
                                        if (next.has(question.id)) next.delete(question.id)
                                        else next.add(question.id)
                                        return next
                                    })
                                }
                            >
                                <Text style={styles.link}>
                                    {skipped.has(question.id) ? 'Answer question' : 'Skip question'}
                                </Text>
                            </Pressable44>
                        </View>
                    ))}
                </ScrollView>
            ) : (
                <>
                    <Text style={styles.body}>
                        This form needs the web app. Open the chat there to answer, or dismiss it to continue.
                    </Text>
                    {webUrl ? (
                        <Pressable44
                            style={styles.textAction}
                            onPress={() => openReplyUrl(webUrl, 'markdown')}
                            accessibilityRole="link"
                        >
                            <Text style={styles.link}>Open chat on web</Text>
                        </Pressable44>
                    ) : null}
                </>
            )}
            <View style={styles.actions}>
                {disabled ? <ActivityIndicator accessibilityLabel="Sending form response" color={colors.ink} /> : null}
                <Pressable44
                    disabled={disabled}
                    accessibilityLabel="Dismiss form"
                    style={[styles.action, disabled && styles.disabled]}
                    onPress={() => void submit(true)}
                >
                    <Text style={styles.label}>Dismiss</Text>
                </Pressable44>
                {questions ? (
                    <Pressable44
                        disabled={disabled || !complete}
                        accessibilityLabel="Submit answers"
                        accessibilityState={{ disabled: disabled || !complete, busy }}
                        style={[styles.action, (disabled || !complete) && styles.disabled]}
                        onPress={() => void submit(false)}
                    >
                        <Text style={styles.label}>Submit answers</Text>
                    </Pressable44>
                ) : null}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    panel: { margin: 10, padding: 12, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.card, gap: 8 },
    scroll: { maxHeight: 300 },
    questions: { gap: 20 },
    question: { gap: 8 },
    field: { gap: 8 },
    label: { ...type.bodyStrong, color: colors.ink },
    body: { ...type.body, color: colors.ink },
    detail: { ...type.meta, color: colors.secondary },
    link: { ...type.meta, color: colors.blue },
    option: { padding: 12, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.option, gap: 4 },
    selected: { borderColor: colors.blue, backgroundColor: colors.sunken },
    input: {
        ...inputReset,
        ...type.input,
        color: colors.ink,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.option,
        padding: 12,
        minHeight: 44,
    },
    actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 8 },
    action: {
        paddingHorizontal: 12,
        minHeight: 34,
        justifyContent: 'center',
        backgroundColor: colors.sunken,
        borderRadius: radii.pill,
    },
    textAction: { minHeight: 34, justifyContent: 'center' },
    disabled: { opacity: 0.45 },
}))
