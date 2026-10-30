import { templateLibraryUrl, templateSectionFor, templateUrlInSection } from './templateSection'

describe('templateSection', () => {
    test.each([
        ['/project/2/transactional/library', '/transactional/library/templates/t1', '/transactional/library'],
        [
            '/project/2/transactional/library/templates/t9',
            '/transactional/library/templates/t1',
            '/transactional/library',
        ],
        ['/project/2/broadcasts/library', '/broadcasts/library/templates/t1', '/broadcasts/library'],
        ['/project/2/workflows/library', '/workflows/library/templates/t1', '/workflows/library'],
        // A path that only shares the prefix is not the Transactional section.
        ['/project/2/transactionalish/library', '/workflows/library/templates/t1', '/workflows/library'],
    ])('opened from %s keeps links in its section', (pathname, expectedTemplateUrl, expectedLibraryUrl) => {
        const section = templateSectionFor(pathname)
        expect(templateUrlInSection('t1', section)).toBe(expectedTemplateUrl)
        expect(templateLibraryUrl(section)).toBe(expectedLibraryUrl)
    })
})
