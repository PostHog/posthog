package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/posthog/posthog/services/prom-compat/internal/api"
	"github.com/posthog/posthog/services/prom-compat/internal/config"
	"github.com/posthog/posthog/services/prom-compat/internal/storage"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	cfg, err := config.Load()
	if err != nil {
		slog.Error("config load failed", "err", err)
		os.Exit(1)
	}

	storeClient, err := storage.NewClient(cfg.ClickHouse)
	if err != nil {
		slog.Error("clickhouse client init failed", "err", err)
		os.Exit(1)
	}
	defer func() { _ = storeClient.Close() }()

	srv := &http.Server{
		Addr:              cfg.Host + ":" + cfg.Port,
		Handler:           api.NewServer(api.Deps{Storage: storeClient}),
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		slog.Info("prom-compat listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("listen failed", "err", err)
			os.Exit(1)
		}
	}()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh
	slog.Info("shutdown initiated")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		slog.Error("shutdown error", "err", err)
		os.Exit(1)
	}
	slog.Info("shutdown complete")
}
