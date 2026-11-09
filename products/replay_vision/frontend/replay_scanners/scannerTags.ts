// Tags from other products can contain commas. The scanner API rejects those, so a scanner can never carry one.
export function isUnusableScannerTag(tag: string): boolean {
    return tag.includes(',')
}
