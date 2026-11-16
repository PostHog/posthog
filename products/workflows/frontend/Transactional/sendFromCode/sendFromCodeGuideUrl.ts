import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

// pinned: URL search param and value, the domain-ready card links to the guide with them
export const SEND_FROM_CODE_GUIDE_PARAM = 'guide'
export const SEND_FROM_CODE_GUIDE_VALUE = 'send-from-code'

/** Transactional emails with the send-from-code guide open, while no email came from code yet. */
export const sendFromCodeGuideUrl = (): string =>
    combineUrl(urls.transactional(), { [SEND_FROM_CODE_GUIDE_PARAM]: SEND_FROM_CODE_GUIDE_VALUE }).url
