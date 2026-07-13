// Formats integer cents as a dollar string: 123456 -> "$1,234.56".
export function formatCents(cents) {
  const sign = cents < 0 ? '-' : ''
  const abs = Math.abs(Math.trunc(cents))
  const dollars = Math.trunc(abs / 100)
  const remainder = String(abs % 100).padStart(2, '0')
  return `${sign}$${dollars.toLocaleString('en-US')}.${remainder}`
}
