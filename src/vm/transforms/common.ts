import { PluginObj } from '@babel/core'
import * as types from '@babel/types'

import { PluginsServer } from '../../types'

export type PluginGen = (server: PluginsServer) => (param: { types: typeof types }) => PluginObj
