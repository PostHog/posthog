import type { SpanTreeNode } from '~/queries/schema/schema-general'

const ms = (value: number): number => value * 1_000_000

function edge(
    parent: [string, string] | null,
    child: [string, string],
    p50Ms: number,
    count: number,
    startOffsetMs: number,
    errorCount = 0
): SpanTreeNode {
    return {
        parent_service: parent ? parent[0] : '',
        parent_name: parent ? parent[1] : '<ROOT>',
        service_name: child[0],
        name: child[1],
        count,
        total_duration_nano: ms(p50Ms) * count,
        avg_duration_nano: ms(p50Ms * 1.1),
        p50_duration_nano: ms(p50Ms),
        p95_duration_nano: ms(p50Ms * 1.8),
        p99_duration_nano: ms(p50Ms * 2.6),
        p999_duration_nano: ms(p50Ms * 3.4),
        error_count: errorCount,
        avg_start_offset_nano: ms(startOffsetMs),
    }
}

const CHECKOUT: [string, string] = ['checkout-api', 'POST /api/v2/checkout/confirm']
const AUTH: [string, string] = ['auth', 'auth.verify_session']
const ORDERS: [string, string] = ['checkout-api', 'orders.load_cart']
const ORDERS_DB: [string, string] = ['postgres', 'SELECT cart_items WHERE cart_id = $1']
const PRICING: [string, string] = ['pricing', 'pricing.quote']
const PRICING_RULES: [string, string] = ['pricing', 'rules.evaluate_promotions']
const INVENTORY: [string, string] = ['inventory-worker', 'inventory.reserve_stock']
const INVENTORY_LOCK: [string, string] = ['redis', 'SET NX lock:sku']
const INVENTORY_DB: [string, string] = ['postgres', 'UPDATE stock SET reserved = reserved + $1']
const PAYMENTS: [string, string] = ['payments', 'payments.charge']
const PAYMENTS_HTTP: [string, string] = ['payments', 'HTTP POST api.payments.example.com/v1/charges']
const FRAUD: [string, string] = ['fraud', 'fraud.score_transaction']
const NOTIFY: [string, string] = ['notifications', 'notifications.enqueue_receipt']

const TINY_CACHE_READS = ['currency', 'locale', 'tax_region', 'feature_flags', 'shipping_zones', 'gift_wrap'].map(
    (key): [string, string] => ['redis', `GET config:${key}`]
)

function cacheReads(scale: number): SpanTreeNode[] {
    return TINY_CACHE_READS.map((child, i) => edge(PRICING, child, 0.4 * scale + i * 0.05, 1800, 2 + i))
}

/** A checkout request's call tree in the current window: payments slowed down, pricing sped up,
 *  fraud scoring is new and the inventory row lock is gone. */
export const SPAN_TREE_CURRENT: SpanTreeNode[] = [
    edge(null, CHECKOUT, 640, 1800, 0, 12),
    edge(CHECKOUT, AUTH, 38, 1800, 1),
    edge(CHECKOUT, ORDERS, 62, 1800, 40),
    edge(ORDERS, ORDERS_DB, 48, 1800, 42),
    edge(CHECKOUT, PRICING, 70, 1800, 105),
    edge(PRICING, PRICING_RULES, 44, 1800, 108),
    ...cacheReads(1),
    edge(CHECKOUT, INVENTORY, 96, 1790, 180),
    edge(INVENTORY, INVENTORY_LOCK, 3, 1790, 181),
    edge(CHECKOUT, PAYMENTS, 290, 1780, 280, 12),
    edge(PAYMENTS, PAYMENTS_HTTP, 240, 1780, 290, 12),
    edge(PAYMENTS, FRAUD, 36, 1780, 282),
    edge(CHECKOUT, NOTIFY, 9, 6, 580),
]

export const SPAN_TREE_PREVIOUS: SpanTreeNode[] = [
    edge(null, CHECKOUT, 520, 1700, 0, 4),
    edge(CHECKOUT, AUTH, 37, 1700, 1),
    edge(CHECKOUT, ORDERS, 60, 1700, 40),
    edge(ORDERS, ORDERS_DB, 47, 1700, 42),
    edge(CHECKOUT, PRICING, 118, 1700, 105),
    edge(PRICING, PRICING_RULES, 90, 1700, 108),
    ...cacheReads(1.1),
    edge(CHECKOUT, INVENTORY, 92, 1700, 180),
    edge(INVENTORY, INVENTORY_LOCK, 3, 1700, 181),
    edge(INVENTORY, INVENTORY_DB, 61, 1700, 186),
    edge(CHECKOUT, PAYMENTS, 168, 1690, 280, 4),
    edge(PAYMENTS, PAYMENTS_HTTP, 150, 1690, 290, 4),
    edge(CHECKOUT, NOTIFY, 5, 4, 580),
]
