package storage

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/posthog/posthog/services/prom-compat/internal/config"
)

func TestPingFailsWhenUnreachable(t *testing.T) {
	// clickhouse.Open is lazy — failures surface at Ping/query time.
	cfg := config.ClickHouseConfig{
		Host:         "127.0.0.1",
		Port:         "1", // reserved, will refuse connections
		User:         "default",
		Database:     "default",
		MaxOpenConns: 1,
		MaxIdleConns: 1,
		DialTimeout:  500 * time.Millisecond,
		ReadTimeout:  1 * time.Second,
	}
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatalf("NewClient should not error on lazy open, got: %v", err)
	}
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := c.Ping(ctx); err == nil {
		t.Fatal("expected Ping to fail against an unreachable host")
	}
}

func TestNilClientPing(t *testing.T) {
	var c *Client
	if err := c.Ping(context.Background()); err == nil {
		t.Fatal("expected error pinging a nil client")
	}
}

// TestClientPingIntegration verifies a real connection. Skipped unless
// PROM_COMPAT_IT=1 is set; designed for the local hogli stack where CH
// listens on localhost:9000 with user "default" and no password.
func TestClientPingIntegration(t *testing.T) {
	if os.Getenv("PROM_COMPAT_IT") == "" {
		t.Skip("set PROM_COMPAT_IT=1 to run integration tests against a real ClickHouse")
	}
	cfg := config.ClickHouseConfig{
		Host:         envOr("CLICKHOUSE_LOGS_CLUSTER_HOST", "localhost"),
		Port:         envOr("CLICKHOUSE_LOGS_CLUSTER_PORT", "9000"),
		User:         envOr("CLICKHOUSE_LOGS_CLUSTER_USER", "default"),
		Password:     os.Getenv("CLICKHOUSE_LOGS_CLUSTER_PASSWORD"),
		Database:     envOr("CLICKHOUSE_LOGS_CLUSTER_DATABASE", "default"),
		MaxOpenConns: 4,
		MaxIdleConns: 2,
		MaxLifetime:  time.Minute,
		DialTimeout:  3 * time.Second,
		ReadTimeout:  10 * time.Second,
	}
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.Ping(ctx); err != nil {
		t.Fatalf("Ping: %v", err)
	}
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
