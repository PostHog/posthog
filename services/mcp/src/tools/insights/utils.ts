export const isShortId = (id: string): boolean => {
    return /^[A-Za-z0-9]{8}$/.test(id)
}
