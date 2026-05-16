package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/posthog/posthog/services/llm-gateway/internal/config"
	"github.com/posthog/posthog/services/llm-gateway/internal/server"
)

func main() {
	settings, err := config.Load()
	if err != nil {
		log.Fatalf("load settings: %v", err)
	}

	app, err := server.New(settings)
	if err != nil {
		log.Fatalf("create server: %v", err)
	}
	defer app.Close()

	srv := &http.Server{
		Addr:              ":" + settings.Port,
		Handler:           app.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       settings.RequestTimeout + 10*time.Second,
		WriteTimeout:      settings.StreamingTimeout + 10*time.Second,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		log.Printf("LLM Gateway ready on %s", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("server failed: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("server shutdown failed: %v", err)
	}
}
