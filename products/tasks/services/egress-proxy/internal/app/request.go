package app

import (
	"context"
	"net/http"
	"time"
)

func boundedRequest(w http.ResponseWriter, r *http.Request, timeout time.Duration) (*http.Request, context.CancelFunc) {
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	deadline, _ := ctx.Deadline()
	controller := http.NewResponseController(w)
	if controller.SetReadDeadline(deadline) != nil || controller.SetWriteDeadline(deadline) != nil {
		cancel()
		panic(http.ErrAbortHandler)
	}
	return r.WithContext(ctx), cancel
}
