import { asRecord } from '@/lib/records'

import type { ClassicForm } from './classicMessages'

export interface ClassicFormField {
    id: string
    label: string
    type: 'select' | 'multi_select' | 'text' | 'number' | 'toggle'
    options: { value: string; description?: string }[]
    allowCustom: boolean
    optional: boolean
    min?: number
    max?: number
    step?: number
    initial?: string
    placeholder?: string
}

export interface ClassicFormQuestion {
    id: string
    title: string
    question: string
    fields: ClassicFormField[]
}

export type ClassicFormAnswers = Record<string, string | string[]>

export interface ClassicFormDraft {
    answers: ClassicFormAnswers
    custom: Record<string, string>
    skipped: readonly string[]
}

function fieldFrom(data: Record<string, unknown>, composite: boolean): ClassicFormField | null {
    if (typeof data.id !== 'string' || !data.id.trim()) return null
    const rawType = data.type ?? (composite ? undefined : 'select')
    const type = rawType === 'dropdown' ? 'select' : rawType === 'slider' ? 'number' : rawType
    if (type !== 'select' && type !== 'multi_select' && type !== 'text' && type !== 'number' && type !== 'toggle') {
        return null
    }
    const options = Array.isArray(data.options)
        ? data.options.flatMap((value) => {
              const option = asRecord(value)
              return typeof option?.value === 'string' && option.value.trim()
                  ? [
                        {
                            value: option.value,
                            description: typeof option.description === 'string' ? option.description : undefined,
                        },
                    ]
                  : []
          })
        : []
    const allowCustom = !composite && data.allow_custom_answer !== false
    if ((type === 'select' || type === 'multi_select') && !options.length && !allowCustom) return null
    const min = typeof data.min === 'number' ? data.min : rawType === 'slider' ? 0 : undefined
    const max = typeof data.max === 'number' ? data.max : rawType === 'slider' ? 100 : undefined
    return {
        id: data.id,
        label: typeof data.label === 'string' ? data.label : '',
        type,
        options,
        allowCustom,
        optional: data.optional === true,
        min,
        max,
        step: typeof data.step === 'number' ? data.step : rawType === 'slider' ? 1 : undefined,
        initial: type === 'toggle' ? 'false' : rawType === 'slider' ? String(min) : undefined,
        placeholder: typeof data.placeholder === 'string' ? data.placeholder : undefined,
    }
}

export function classicFormQuestions(form: ClassicForm): ClassicFormQuestion[] | null {
    const questions: ClassicFormQuestion[] = []
    const fieldIds = new Set<string>()
    for (const question of form.questions) {
        if (typeof question.id !== 'string' || typeof question.question !== 'string') return null
        const composite = question.type === 'multi_field'
        const rawFields = composite ? question.fields : [question]
        if (!Array.isArray(rawFields) || !rawFields.length) return null
        const fields: ClassicFormField[] = []
        for (const raw of rawFields) {
            const data = asRecord(raw)
            const field = data ? fieldFrom(data, composite) : null
            if (!field || fieldIds.has(field.id)) return null
            fieldIds.add(field.id)
            fields.push(field)
        }
        questions.push({
            id: question.id,
            title: typeof question.title === 'string' ? question.title : '',
            question: question.question,
            fields,
        })
    }
    return questions.length ? questions : null
}

export function initialClassicFormAnswers(questions: readonly ClassicFormQuestion[]): ClassicFormAnswers {
    return Object.fromEntries(
        questions.flatMap((question) =>
            question.fields.flatMap((field) => (field.initial !== undefined ? [[field.id, field.initial]] : []))
        )
    )
}

export function combinedClassicFormAnswers(
    questions: readonly ClassicFormQuestion[],
    answers: ClassicFormAnswers,
    custom: Readonly<Record<string, string>>
): ClassicFormAnswers {
    const combined = { ...answers }
    for (const question of questions) {
        for (const field of question.fields) {
            if (field.type !== 'multi_select') continue
            const selected = answers[field.id]
            const additional = field.allowCustom
                ? (custom[field.id] ?? '')
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean)
                : []
            combined[field.id] = [...(Array.isArray(selected) ? selected : []), ...additional]
        }
    }
    return combined
}

export function submittedClassicFormAnswers(
    questions: readonly ClassicFormQuestion[],
    answers: ClassicFormAnswers
): ClassicFormAnswers {
    return Object.fromEntries(
        questions.flatMap((question) =>
            question.fields.flatMap((field): [string, string | string[]][] => {
                const value = answers[field.id]
                if (value === undefined) return []
                if (!Array.isArray(value)) return [[field.id, value]]
                const predefined = new Set(field.options.map((option) => option.value))
                const exactSelections = new Set(value.filter((item) => predefined.has(item)))
                const unique = new Map<string, string>()
                for (const item of value) {
                    const matching = (option: ClassicFormField['options'][number]): boolean =>
                        option.value.toLowerCase() === item.trim().toLowerCase()
                    const canonical = predefined.has(item)
                        ? item
                        : (field.options.find((option) => exactSelections.has(option.value) && matching(option))
                              ?.value ??
                          field.options.find(matching)?.value ??
                          item.trim())
                    const key = predefined.has(canonical) ? `option:${canonical}` : `custom:${canonical.toLowerCase()}`
                    if (!unique.has(key)) unique.set(key, canonical)
                }
                return [[field.id, [...unique.values()]]]
            })
        )
    )
}

export function classicFormComplete(questions: readonly ClassicFormQuestion[], answers: ClassicFormAnswers): boolean {
    return questions.every((question) =>
        question.fields.every((field) => {
            const value = answers[field.id]
            if (value === undefined || value === '' || (Array.isArray(value) && !value.length)) return field.optional
            if (field.type === 'multi_select') {
                return (
                    Array.isArray(value) &&
                    value.every(
                        (option) =>
                            typeof option === 'string' &&
                            option.trim() &&
                            (field.allowCustom || field.options.some((candidate) => candidate.value === option))
                    )
                )
            }
            if (typeof value !== 'string' || !value.trim()) return false
            if (field.type === 'toggle') return value === 'true' || value === 'false'
            if (field.type === 'select')
                return field.allowCustom || field.options.some((option) => option.value === value)
            if (field.type === 'number') {
                const number = Number(value)
                if (
                    !Number.isFinite(number) ||
                    (field.min !== undefined && number < field.min) ||
                    (field.max !== undefined && number > field.max)
                )
                    return false
                if (field.step !== undefined && field.step > 0) {
                    const steps = (number - (field.min ?? 0)) / field.step
                    if (Math.abs(steps - Math.round(steps)) > 1e-8) return false
                }
            }
            return true
        })
    )
}
