import { describe, expect, it } from 'vitest'

import { type FileTree, GitRepoCache, handleInfoRefs, synthesizeRepo } from '@/lib/git'

describe('synthesizeRepo', () => {
    it('produces objects and a head SHA for a simple file tree', () => {
        const files: FileTree = {
            'README.md': '# Hello',
            'src/index.ts': 'console.log("hi")',
        }

        const { objects, headSha } = synthesizeRepo(files)

        expect(headSha).toMatch(/^[0-9a-f]{40}$/)
        expect(objects.length).toBeGreaterThan(0)

        // Should have: 2 blobs + 2 trees (src/ and root) + 1 commit = 5
        expect(objects).toHaveLength(5)
    })

    it('is deterministic — same content produces same SHA', () => {
        const files: FileTree = { 'a.txt': 'hello' }

        const r1 = synthesizeRepo(files)
        const r2 = synthesizeRepo(files)

        expect(r1.headSha).toBe(r2.headSha)
        expect(r1.objects.length).toBe(r2.objects.length)
    })

    it('produces different SHAs for different content', () => {
        const r1 = synthesizeRepo({ 'a.txt': 'v1' })
        const r2 = synthesizeRepo({ 'a.txt': 'v2' })

        expect(r1.headSha).not.toBe(r2.headSha)
    })

    it('handles nested directories', () => {
        const files: FileTree = {
            'a/b/c/deep.txt': 'deep content',
        }

        const { objects, headSha } = synthesizeRepo(files)
        expect(headSha).toMatch(/^[0-9a-f]{40}$/)

        // 1 blob + 3 trees (c/, b/, a/ → root merges with a/) + root tree + commit
        // Actually: 1 blob + tree(c) + tree(b) + tree(a) + tree(root) + commit = 6
        // Wait: a/b/c/deep.txt → dirs: a → b → c → file: deep.txt
        // Trees: c (has deep.txt), b (has c), a (has b), root (has a) = 4 trees
        // Total: 1 blob + 4 trees + 1 commit = 6
        expect(objects).toHaveLength(6)
    })

    it('handles empty file content', () => {
        const files: FileTree = { 'empty.txt': '' }
        const { objects, headSha } = synthesizeRepo(files)

        expect(headSha).toMatch(/^[0-9a-f]{40}$/)
        expect(objects).toHaveLength(3) // blob + tree + commit
    })
})

describe('handleInfoRefs', () => {
    it('returns correct content type', () => {
        const response = handleInfoRefs('a'.repeat(40))

        expect(response.headers.get('Content-Type')).toBe('application/x-git-upload-pack-advertisement')
    })

    it('includes the head SHA in the response body', async () => {
        const sha = 'deadbeef'.repeat(5)
        const response = handleInfoRefs(sha)
        const body = await response.text()

        expect(body).toContain(sha)
        expect(body).toContain('refs/heads/main')
    })

    it('advertises required capabilities', async () => {
        const response = handleInfoRefs('a'.repeat(40))
        const body = await response.text()

        expect(body).toContain('side-band-64k')
        expect(body).toContain('symref=HEAD:refs/heads/main')
    })
})

describe('GitRepoCache', () => {
    it('returns cached result for identical content', () => {
        const cache = new GitRepoCache()
        const files: FileTree = { 'a.txt': 'hello' }

        const r1 = cache.getOrBuild('test', files)
        const r2 = cache.getOrBuild('test', files)

        expect(r1.headSha).toBe(r2.headSha)
        expect(r1.contentHash).toBe(r2.contentHash)
    })

    it('invalidates when content changes', () => {
        const cache = new GitRepoCache()

        const r1 = cache.getOrBuild('test', { 'a.txt': 'v1' })
        const r2 = cache.getOrBuild('test', { 'a.txt': 'v2' })

        expect(r1.headSha).not.toBe(r2.headSha)
        expect(r1.contentHash).not.toBe(r2.contentHash)
    })

    it('maintains separate caches per key', () => {
        const cache = new GitRepoCache()

        const r1 = cache.getOrBuild('a', { 'a.txt': 'a' })
        const r2 = cache.getOrBuild('b', { 'b.txt': 'b' })

        expect(r1.headSha).not.toBe(r2.headSha)
    })

    it('clears all entries on invalidateAll', () => {
        const cache = new GitRepoCache()
        const files: FileTree = { 'a.txt': 'hello' }

        const r1 = cache.getOrBuild('test', files)
        cache.invalidateAll()
        const r2 = cache.getOrBuild('test', files)

        // Same content so same hash, but it was rebuilt (no way to test this directly,
        // just verify it doesn't throw)
        expect(r1.headSha).toBe(r2.headSha)
    })
})
