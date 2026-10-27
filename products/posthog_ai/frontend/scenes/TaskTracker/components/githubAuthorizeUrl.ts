import api from 'lib/api'
import { urls } from 'scenes/urls'

export const githubAuthorizeUrl = api.integrations.authorizeUrl({ kind: 'github', next: urls.taskTracker() })
