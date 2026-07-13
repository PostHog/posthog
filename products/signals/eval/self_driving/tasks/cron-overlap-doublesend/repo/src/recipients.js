// Collapse duplicate subscriptions - users subscribed through multiple
// projects should get a single digest. Keeps the most recent subscription
// (rows are ordered oldest-first), hence the reverse scan.
export function dedupeRecipients(subscriptions) {
  const seen = Object.create(null)
  const result = []
  for (let index = subscriptions.length - 1; index >= 0; index--) {
    const key = subscriptions[index].email.trim().toLowerCase()
    if (seen[key]) {
      continue
    }
    seen[key] = true
    result.unshift(subscriptions[index])
  }
  return result
}
