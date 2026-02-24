import { LemonTable, LemonTableColumns } from "@posthog/lemon-ui";
import { useValues } from "kea";
import { useEffect, useMemo, useState } from "react";

import { getColorVar } from "lib/colors";
import { AppMetricSummary } from "lib/components/AppMetrics/AppMetricSummary";
import { AppMetricsTrends } from "lib/components/AppMetrics/AppMetricsTrends";
import {
  AppMetricsTimeSeriesResponse,
  appMetricsLogic,
  loadAppMetricsTotals,
  type AppMetricsTotalsResponse,
} from "lib/components/AppMetrics/appMetricsLogic";

import { isOptOutEligibleAction } from "./hogflows/steps/types";
import { HogFlow } from "./hogflows/types";

type WorkflowSummaryMetric =
  | "started"
  | "in_progress"
  | "persons_messaged"
  | "completed";
type MessageMetric = "sent" | "delivered" | "opened" | "unsubscribed";

type MessageMetricRow = {
  id: string;
  message: string;
  sent: number;
  delivered: number;
  opened: number;
  unsubscribed: number;
};

const WORKFLOW_SUMMARY_METRICS: Record<
  WorkflowSummaryMetric,
  {
    name: string;
    description: string;
    color: string;
    metricNames: string[];
  }
> = {
  started: {
    name: "Started",
    description: "Total number of workflow runs started",
    color: getColorVar("success"),
    metricNames: ["started", "triggered"],
  },
  in_progress: {
    name: "In progress",
    description: "Total number of workflow runs currently in progress",
    color: getColorVar("warning"),
    metricNames: ["in_progress"],
  },
  persons_messaged: {
    name: "Persons messaged",
    description: "Total number of persons messaged by this workflow",
    color: getColorVar("primary"),
    metricNames: ["persons_messaged", "billable_invocation"],
  },
  completed: {
    name: "Completed",
    description: "Total number of workflow runs completed",
    color: getColorVar("success"),
    metricNames: ["completed", "succeeded"],
  },
};

const MESSAGE_METRICS: MessageMetric[] = [
  "sent",
  "delivered",
  "opened",
  "unsubscribed",
];

export function WorkflowMetricsSummary({
  logic,
  workflow,
}: {
  logic: ReturnType<typeof appMetricsLogic>;
  workflow: HogFlow;
}): JSX.Element {
  const {
    appMetricsTrendsLoading,
    getSingleTrendSeries,
    appMetricsTrends,
    params,
    currentTeam,
    getDateRangeAbsolute,
  } = useValues(logic);

  const [messageTotalsByActionId, setMessageTotalsByActionId] = useState<
    Record<string, Partial<Record<MessageMetric, number>>>
  >({});
  const [messageTotalsLoading, setMessageTotalsLoading] = useState(false);

  const messageActions = useMemo(
    () => workflow.actions.filter(isOptOutEligibleAction),
    [workflow.actions],
  );

  const metricNameBySummaryMetric = useMemo(() => {
    return (
      Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]
    ).reduce(
      (acc, key) => {
        const metric = WORKFLOW_SUMMARY_METRICS[key];
        const selectedMetricName =
          metric.metricNames.find((metricName) =>
            appMetricsTrends?.series.some(
              (series) => series.name === metricName,
            ),
          ) ?? metric.metricNames[0];
        acc[key] = selectedMetricName;
        return acc;
      },
      {} as Record<WorkflowSummaryMetric, string>,
    );
  }, [appMetricsTrends]);

  const workflowSummaryTrends =
    useMemo((): AppMetricsTimeSeriesResponse | null => {
      if (!appMetricsTrends) {
        return null;
      }

      return {
        labels: appMetricsTrends.labels,
        series: (
          Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]
        ).map((summaryMetric) => {
          const selectedMetricName = metricNameBySummaryMetric[summaryMetric];
          const matchedSeries = appMetricsTrends.series.find(
            (series) => series.name === selectedMetricName,
          );

          return {
            name: WORKFLOW_SUMMARY_METRICS[summaryMetric].name,
            values:
              matchedSeries?.values ??
              Array.from({ length: appMetricsTrends.labels.length }, () => 0),
          };
        }),
      };
    }, [appMetricsTrends, metricNameBySummaryMetric]);

  const messageMetricsRows = useMemo<MessageMetricRow[]>(() => {
    return messageActions.map((action) => {
      const totals = messageTotalsByActionId[action.id] || {};
      return {
        id: action.id,
        message: action.name,
        sent: totals.sent ?? 0,
        delivered: totals.delivered ?? 0,
        opened: totals.opened ?? 0,
        unsubscribed: totals.unsubscribed ?? 0,
      };
    });
  }, [messageActions, messageTotalsByActionId]);

  const messageMetricsColumns: LemonTableColumns<MessageMetricRow> = useMemo(
    () => [
      {
        title: "Message",
        dataIndex: "message",
        key: "message",
      },
      {
        title: "Sent",
        dataIndex: "sent",
        key: "sent",
        align: "right",
        render: (_, row) => row.sent.toLocaleString(),
      },
      {
        title: "Delivered",
        dataIndex: "delivered",
        key: "delivered",
        align: "right",
        render: (_, row) => row.delivered.toLocaleString(),
      },
      {
        title: "Opened",
        dataIndex: "opened",
        key: "opened",
        align: "right",
        render: (_, row) => row.opened.toLocaleString(),
      },
      {
        title: "Unsubscribed",
        dataIndex: "unsubscribed",
        key: "unsubscribed",
        align: "right",
        render: (_, row) => row.unsubscribed.toLocaleString(),
      },
    ],
    [],
  );

  useEffect(() => {
    let cancelled = false;

    const loadMessageTotals = async (): Promise<void> => {
      setMessageTotalsLoading(true);
      try {
        const dateRange = getDateRangeAbsolute();
        const request = {
          appSource: params.appSource,
          appSourceId: params.appSourceId,
          breakdownBy: ["instance_id", "metric_name"] as const,
          metricName: MESSAGE_METRICS,
          dateFrom: dateRange.dateFrom.toISOString(),
          dateTo: dateRange.dateTo.toISOString(),
        };

        const totalsResponse = await loadAppMetricsTotals(
          request,
          currentTeam?.timezone ?? "UTC",
        );
        if (cancelled) {
          return;
        }

        const nextTotalsByActionId = mapMessageMetricsToActions(totalsResponse);
        setMessageTotalsByActionId(nextTotalsByActionId);
      } finally {
        if (!cancelled) {
          setMessageTotalsLoading(false);
        }
      }
    };

    void loadMessageTotals();

    return () => {
      cancelled = true;
    };
  }, [
    params.appSource,
    params.appSourceId,
    params.dateFrom,
    params.dateTo,
    params.interval,
    currentTeam?.timezone,
    getDateRangeAbsolute,
  ]);

  return (
    <>
      <div className="flex flex-row gap-2 flex-wrap justify-center">
        {(Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]).map(
          (summaryMetric) => {
            const metric = WORKFLOW_SUMMARY_METRICS[summaryMetric];
            const metricName = metricNameBySummaryMetric[summaryMetric];
            return (
              <AppMetricSummary
                key={summaryMetric}
                name={metric.name}
                description={metric.description}
                loading={appMetricsTrendsLoading}
                timeSeries={withDisplayName(
                  getSingleTrendSeries(metricName),
                  metric.name,
                )}
                previousPeriodTimeSeries={withDisplayName(
                  getSingleTrendSeries(metricName, true),
                  metric.name,
                )}
                color={metric.color}
                colorIfZero={getColorVar("muted")}
              />
            );
          },
        )}
      </div>

      <AppMetricsTrends
        appMetricsTrends={workflowSummaryTrends}
        loading={appMetricsTrendsLoading}
      />

      <LemonTable
        columns={messageMetricsColumns}
        dataSource={messageMetricsRows}
        loading={messageTotalsLoading}
        rowKey="id"
        size="small"
        emptyState="No message actions in this workflow"
      />
    </>
  );
}

function withDisplayName(
  series: AppMetricsTimeSeriesResponse | null,
  displayName: string,
): AppMetricsTimeSeriesResponse | null {
  if (!series) {
    return null;
  }

  return {
    labels: series.labels,
    series: series.series.map((item) => ({
      ...item,
      name: displayName,
    })),
  };
}

function mapMessageMetricsToActions(
  totalsResponse: AppMetricsTotalsResponse,
): Record<string, Partial<Record<MessageMetric, number>>> {
  const result: Record<string, Partial<Record<MessageMetric, number>>> = {};

  Object.values(totalsResponse).forEach(({ total, breakdowns }) => {
    const [instanceId, metricName] = breakdowns;
    if (!instanceId || !isMessageMetric(metricName)) {
      return;
    }

    result[instanceId] = result[instanceId] || {};
    result[instanceId][metricName] = total;
  });

  return result;
}

function isMessageMetric(metricName: string): metricName is MessageMetric {
  return MESSAGE_METRICS.includes(metricName as MessageMetric);
}
