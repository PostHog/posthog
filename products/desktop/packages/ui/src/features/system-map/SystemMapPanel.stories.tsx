import type {
  SystemMap,
  SystemMapEvidence,
} from "@posthog/core/system-map/schemas";
import { Button } from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SystemMapPanel } from "./SystemMapView";

const evidence = (path: string, note: string): SystemMapEvidence[] => [
  { path, line: 24, note },
];
const map: SystemMap = {
  summary:
    "A parcel service accepts orders, reserves stock, and books deliveries. Delivery events trigger customer notifications.",
  coverage: [
    {
      path: "src/orders",
      status: "reviewed",
      summary: "Read the order endpoint and service.",
      componentIds: ["order-api", "order-service"],
    },
    {
      path: "src/stock",
      status: "reviewed",
      summary: "Read reservations and the stock ledger.",
      componentIds: ["reservations", "ledger"],
    },
    {
      path: "src/delivery",
      status: "partial",
      summary: "Read booking and tracking. Retry handlers were not inspected.",
      componentIds: ["booking", "tracking"],
    },
    {
      path: "src/notifications",
      status: "reviewed",
      summary: "Read the delivery event handler.",
      componentIds: ["delivery-mail"],
    },
    {
      path: "src/returns",
      status: "not_reviewed",
      summary:
        "Found this module in the source listing. Its code was not read.",
      componentIds: [],
    },
  ],
  areas: [
    {
      id: "orders",
      name: "Orders",
      summary: "Accept orders and track their progress.",
      components: [
        {
          id: "order-api",
          name: "Order API",
          summary: "Validate new orders and pass them to the order service.",
          operations: [
            {
              name: "POST /orders",
              kind: "command",
              summary: "Accept a new order request.",
              evidence: evidence(
                "src/orders/api.ts",
                "The route creates an order.",
              ),
            },
          ],
          evidence: evidence(
            "src/orders/api.ts",
            "The create endpoint passes validated input to the order service.",
          ),
        },
        {
          id: "order-service",
          name: "Order service",
          summary: "Reserve stock before an order enters delivery.",
          operations: [
            {
              name: "createOrder",
              kind: "command",
              summary: "Reserve items and request a parcel booking.",
              evidence: evidence(
                "src/orders/service.ts",
                "The service writes the order and requests delivery.",
              ),
            },
          ],
          evidence: evidence(
            "src/orders/service.ts",
            "The service coordinates stock reservations and delivery requests.",
          ),
        },
      ],
    },
    {
      id: "stock",
      name: "Stock",
      summary: "Track available items and reserve them for orders.",
      components: [
        {
          id: "reservations",
          name: "Reservations",
          summary: "Reserve items and release canceled reservations.",
          operations: [
            {
              name: "reserveItems",
              kind: "command",
              summary: "Reserve the requested stock for an order.",
              evidence: evidence(
                "src/stock/reservations.ts",
                "The function writes a reservation and updates stock.",
              ),
            },
            {
              name: "getReservation",
              kind: "query",
              summary: "Read the current reservation for an order.",
              evidence: evidence(
                "src/stock/reservations.ts",
                "The function reads a reservation without changing it.",
              ),
            },
          ],
          evidence: evidence(
            "src/stock/reservations.ts",
            "Reservation writes update the stock ledger.",
          ),
        },
        {
          id: "ledger",
          name: "Stock ledger",
          summary: "Store stock levels and active reservations.",
          operations: [],
          evidence: evidence(
            "src/stock/ledger.ts",
            "The ledger contains stock and reservation records.",
          ),
        },
      ],
    },
    {
      id: "delivery",
      name: "Delivery",
      summary: "Book parcels and receive delivery updates.",
      components: [
        {
          id: "booking",
          name: "Parcel booking",
          summary: "Create delivery requests for accepted orders.",
          operations: [
            {
              name: "bookParcel",
              kind: "command",
              summary: "Send a booking request to the delivery provider.",
              evidence: evidence(
                "src/delivery/booking.ts",
                "The function sends a request to the provider.",
              ),
            },
          ],
          evidence: evidence(
            "src/delivery/booking.ts",
            "The booking service creates a delivery record.",
          ),
        },
        {
          id: "tracking",
          name: "Delivery tracking",
          summary: "Process delivery updates and publish status events.",
          operations: [
            {
              name: "handleDeliveryUpdate",
              kind: "command",
              summary: "Publish an event for a delivery update.",
              evidence: evidence(
                "src/delivery/tracking.ts",
                "The handler publishes a status event.",
              ),
            },
          ],
          evidence: evidence(
            "src/delivery/tracking.ts",
            "The handler publishes delivery status events.",
          ),
        },
      ],
    },
    {
      id: "notifications",
      name: "Notifications",
      summary: "Send updates when a delivery changes state.",
      components: [
        {
          id: "delivery-mail",
          name: "Delivery messages",
          summary: "Build messages from delivery status events.",
          operations: [
            {
              name: "handleDeliveryEvent",
              kind: "unknown",
              summary:
                "Pass a delivery message to a sender whose implementation was not inspected.",
              evidence: evidence(
                "src/notifications/delivery.ts",
                "The handler calls the injected sender.",
              ),
            },
          ],
          evidence: evidence(
            "src/notifications/delivery.ts",
            "The event handler builds a delivery message.",
          ),
        },
      ],
    },
  ],
  relationships: [
    {
      source: "order-api",
      target: "order-service",
      kind: "calls",
      summary: "The API delegates order creation to the service.",
      assumptions: [],
      evidence: evidence(
        "src/orders/api.ts",
        "createOrder receives the validated order.",
      ),
    },
    {
      source: "order-service",
      target: "reservations",
      kind: "calls",
      summary: "Order creation reserves stock before booking a parcel.",
      assumptions: [
        {
          summary:
            "A successful reservation covers every requested item before booking starts.",
          evidence: evidence(
            "src/orders/service.ts",
            "The caller books the parcel after reserveItems resolves without a second stock check.",
          ),
        },
      ],
      evidence: evidence(
        "src/orders/service.ts",
        "reserveItems must succeed before booking starts.",
      ),
    },
    {
      source: "reservations",
      target: "ledger",
      kind: "data",
      summary: "Reservations update stock levels.",
      assumptions: [],
      evidence: evidence(
        "src/stock/reservations.ts",
        "The reservation transaction writes the ledger.",
      ),
    },
    {
      source: "order-service",
      target: "booking",
      kind: "calls",
      summary: "An accepted order creates a parcel booking.",
      assumptions: [],
      evidence: evidence(
        "src/orders/service.ts",
        "bookParcel receives the accepted order.",
      ),
    },
    {
      source: "tracking",
      target: "delivery-mail",
      kind: "event",
      summary: "Delivery status events trigger a message.",
      assumptions: [],
      evidence: evidence(
        "src/notifications/delivery.ts",
        "The handler subscribes to delivery status changes.",
      ),
    },
  ],
  limitations: [
    "The external delivery provider was not inspected. These connections describe the source in this repository.",
  ],
};

const meta = {
  title: "Context/System map",
  component: SystemMapPanel,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="h-screen bg-background text-foreground">
        <Story />
      </div>
    ),
  ],
  args: {
    repositoryPicker: (
      <Button size="sm" variant="outline">
        parcel-service
      </Button>
    ),
    hasRepository: true,
    running: false,
    onAnalyze: () => {},
    onCancel: () => {},
  },
} satisfies Meta<typeof SystemMapPanel>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};
export const Analyzing: Story = { args: { running: true } };
export const Restoring: Story = { args: { restoring: true } };
export const RestoreFailed: Story = {
  args: {
    error: "Check your connection and retry, or analyze the repository again.",
    onRetryLoad: () => {},
  },
};
export const Failed: Story = {
  args: { error: "The agent returned an invalid map. Try the analysis again." },
};
export const Overview: Story = {
  args: {
    result: {
      map,
      taskId: "example-task",
      runId: "example-run",
      analyzedAt: "2026-09-23T10:00:00Z",
    },
  },
};
export const NoRepository: Story = {
  args: {
    repositoryPicker: (
      <Button size="sm" variant="outline">
        Select repository
      </Button>
    ),
    hasRepository: false,
  },
};
export const AnalysisFailedWithSavedMap: Story = {
  args: {
    result: Overview.args.result,
    error: "Analysis ended without a map. Try the analysis again.",
  },
};
export const AnalyzingWithSavedMap: Story = {
  args: { result: Overview.args.result, running: true },
};
export const Disconnected: Story = {
  args: {
    result: { ...Overview.args.result, map: { ...map, relationships: [] } },
  },
};
