/**
 * Thin compatibility shim — the previous zip-based loader was replaced with
 * the KV-backed cache in `./kv-store.ts`. New callers should import from there
 * directly. Kept here only to spare unrelated import chains from churning in
 * the same change; we can delete this file once nothing imports it.
 */
export { getManifest, getResourceText } from './kv-store'
