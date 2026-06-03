// Package storage wraps ClickHouse access for prom-compat.
//
// PR 2 ships only the connection pool + Ping. The full storage.Querier
// adapter that the upstream Prometheus engine talks to lands in PR 5.
package storage

import (
	"context"
	"fmt"

	"github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"

	"github.com/posthog/posthog/services/prom-compat/internal/config"
)

// Client is a pooled ClickHouse connection scoped to the logs cluster.
type Client struct {
	conn driver.Conn
}

// NewClient opens the pool. It does NOT block on a connection; the first
// Ping (or query) will do that. Returning eagerly lets the service start
// when ClickHouse is briefly unavailable; /_readiness reports degraded.
func NewClient(cfg config.ClickHouseConfig) (*Client, error) {
	conn, err := clickhouse.Open(&clickhouse.Options{
		Addr: []string{fmt.Sprintf("%s:%s", cfg.Host, cfg.Port)},
		Auth: clickhouse.Auth{
			Database: cfg.Database,
			Username: cfg.User,
			Password: cfg.Password,
		},
		DialTimeout:     cfg.DialTimeout,
		ReadTimeout:     cfg.ReadTimeout,
		MaxOpenConns:    cfg.MaxOpenConns,
		MaxIdleConns:    cfg.MaxIdleConns,
		ConnMaxLifetime: cfg.MaxLifetime,
		ClientInfo: clickhouse.ClientInfo{
			Products: []struct {
				Name    string
				Version string
			}{
				{Name: "prom-compat", Version: "0.1.0"},
			},
		},
	})
	if err != nil {
		return nil, fmt.Errorf("open clickhouse: %w", err)
	}
	return &Client{conn: conn}, nil
}

// Ping issues a connectivity check honouring the supplied context.
func (c *Client) Ping(ctx context.Context) error {
	if c == nil {
		return fmt.Errorf("nil clickhouse client")
	}
	return c.conn.Ping(ctx)
}

// Close releases all connections in the pool.
func (c *Client) Close() error {
	if c == nil {
		return nil
	}
	return c.conn.Close()
}

// Conn exposes the underlying driver.Conn so later PRs can issue queries.
func (c *Client) Conn() driver.Conn {
	if c == nil {
		return nil
	}
	return c.conn
}
