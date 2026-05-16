FROM golang:1.26.2-bookworm AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /llm-gateway .

FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=builder /llm-gateway /llm-gateway

EXPOSE 8080

CMD ["/llm-gateway"]
