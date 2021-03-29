import { PluginObj } from '@babel/core'
import * as types from '@babel/types'

import { PluginsServer } from '../../../types'

export type PluginGen = (server: PluginsServer, ...args: any[]) => (param: { types: typeof types }) => PluginObj
