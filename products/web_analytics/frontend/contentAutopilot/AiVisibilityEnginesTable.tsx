import { IconInfo } from '@posthog/icons'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import type { AEOEngineSettingApi, CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { engineLabel } from './utils'

export const AiVisibilityEnginesTable = ({
    engines,
    loading,
    frequencyOptions,
    frequencyTooltip,
    noSearchNote,
    disabledReason,
    onChange,
}: {
    engines: AEOEngineSettingApi[]
    loading: boolean
    frequencyOptions: { value: CheckFrequencyEnumApi; label: string }[]
    frequencyTooltip: string
    noSearchNote: string
    disabledReason: (setting: AEOEngineSettingApi) => string | undefined
    onChange: (engine: string, update: Partial<Pick<AEOEngineSettingApi, 'enabled' | 'frequency'>>) => void
}): JSX.Element => (
    <Table fullWidth>
        <TableHeader>
            <TableRow>
                <TableHead expand>Engine</TableHead>
                <TableHead>Checks prompts</TableHead>
                <TableHead>
                    <span className="inline-flex items-center gap-1">
                        How often
                        <Tooltip>
                            <TooltipTrigger delay={0} render={<span aria-label="About how often" />}>
                                <IconInfo />
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">{frequencyTooltip}</TooltipContent>
                        </Tooltip>
                    </span>
                </TableHead>
            </TableRow>
        </TableHeader>
        <TableBody>
            {loading && engines.length === 0
                ? [0, 1, 2].map((row) => (
                      <TableRow key={row}>
                          <TableCell colSpan={3}>
                              <Skeleton className="h-5 w-full" />
                          </TableCell>
                      </TableRow>
                  ))
                : engines.map((setting) => (
                      <TableRow key={setting.engine}>
                          <TableCell>
                              <div className="flex flex-col">
                                  <Text size="xs" render={<span className="font-semibold" />}>
                                      {engineLabel(setting.engine)}
                                  </Text>
                                  {setting.mode === 'no_search' ? (
                                      <Text size="xs" variant="muted" render={<span />}>
                                          {noSearchNote}
                                      </Text>
                                  ) : null}
                              </div>
                          </TableCell>
                          <TableCell>
                              <Switch
                                  aria-label={`${engineLabel(setting.engine)} checks prompts`}
                                  checked={setting.enabled && setting.available}
                                  onCheckedChange={(enabled) => onChange(setting.engine, { enabled })}
                                  disabledReason={disabledReason(setting)}
                                  data-attr="ai-visibility-engine-enabled"
                              />
                          </TableCell>
                          <TableCell>
                              <Select<CheckFrequencyEnumApi>
                                  value={setting.frequency}
                                  onValueChange={(frequency) => frequency && onChange(setting.engine, { frequency })}
                              >
                                  <SelectTrigger
                                      aria-label={`How often ${engineLabel(setting.engine)} checks prompts`}
                                      className="min-w-36"
                                      disabledReason={disabledReason(setting)}
                                      data-attr="ai-visibility-engine-frequency"
                                  >
                                      <SelectValue>
                                          {(value: CheckFrequencyEnumApi | null) =>
                                              frequencyOptions.find((option) => option.value === value)?.label
                                          }
                                      </SelectValue>
                                  </SelectTrigger>
                                  <SelectContent>
                                      {frequencyOptions.map((option) => (
                                          <SelectItem key={option.value} value={option.value}>
                                              {option.label}
                                          </SelectItem>
                                      ))}
                                  </SelectContent>
                              </Select>
                          </TableCell>
                      </TableRow>
                  ))}
        </TableBody>
    </Table>
)
