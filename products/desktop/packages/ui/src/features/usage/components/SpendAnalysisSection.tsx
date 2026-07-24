import { WarningCircle } from "@phosphor-icons/react";
import {
  fillSpendDays,
  type SpendAnalysisWindow,
} from "@posthog/core/billing/spendAnalysisFormat";
import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useSpendAnalysis } from "../useSpendAnalysis";
import { ModelBreakdownCards } from "./ModelBreakdownCards";
import {
  ProductBreakdownCard,
  ToolBreakdownCard,
} from "./SpendBreakdownTables";
import { SpendInsights } from "./SpendInsights";
import { SpendKpiStrip } from "./SpendKpiStrip";
import { SpendOverTimeCard } from "./SpendOverTimeCard";
import { WindowSelector } from "./WindowSelector";

const PRODUCT_SCOPE = "posthog_code";

export function SpendAnalysisSection() {
  const [spendWindow, setSpendWindow] = useState<SpendAnalysisWindow>("30d");
  const { data, isLoading, isFetching, error, refetch } = useSpendAnalysis({
    window: spendWindow,
    product: PRODUCT_SCOPE,
  });

  const filledDays = useMemo(() => {
    if (!data?.by_day) return null;
    return fillSpendDays(
      data.by_day.items,
      data.summary.date_from,
      data.summary.date_to,
    );
  }, [data]);

  return (
    <Flex direction="column" gap="3">
      <Flex align="center" justify="between">
        <Text className="font-medium text-(--gray-9) text-sm">
          Personal spend analysis
        </Text>
        <Flex align="center" gap="4">
          <WindowSelector value={spendWindow} onChange={setSpendWindow} />
          <Button
            size="1"
            variant="soft"
            disabled={isFetching}
            onClick={refetch}
          >
            {isFetching && !isLoading ? <Spinner size="1" /> : "Refresh"}
          </Button>
        </Flex>
      </Flex>

      {error ? (
        <Callout.Root color="red" size="1">
          <Callout.Icon>
            <WarningCircle size={16} />
          </Callout.Icon>
          <Callout.Text>
            <Flex direction="column" gap="2">
              <Text className="text-sm">Couldn't load spend analysis</Text>
              <Text className="text-(--gray-11) text-[13px]">{error}</Text>
              <Button
                size="1"
                variant="outline"
                color="red"
                onClick={refetch}
                className="self-start"
              >
                Try again
              </Button>
            </Flex>
          </Callout.Text>
        </Callout.Root>
      ) : isLoading ? (
        <Flex
          align="center"
          justify="center"
          p="6"
          className="rounded-(--radius-3) border border-(--gray-5)"
        >
          <Spinner size="2" />
        </Flex>
      ) : data ? (
        <>
          <SpendKpiStrip data={data} filledDays={filledDays} />
          {filledDays && <SpendOverTimeCard filledDays={filledDays} />}
          <ModelBreakdownCards
            rows={data.by_model.items}
            scopedCostUsd={data.summary.scoped_cost_usd}
          />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ToolBreakdownCard rows={data.by_tool.items} />
            <ProductBreakdownCard rows={data.by_product.items} />
          </div>
          <SpendInsights data={data} />
        </>
      ) : null}
    </Flex>
  );
}
