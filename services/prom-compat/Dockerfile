FROM golang:1.25.5 AS builder
WORKDIR /code
COPY go.mod go.sum ./
RUN go mod download -x

COPY . ./
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /prom-compat .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /prom-compat /prom-compat
USER nonroot
EXPOSE 9090
ENTRYPOINT ["/prom-compat"]
