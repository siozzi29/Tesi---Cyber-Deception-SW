# Stage 1: Build del binario Go
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /proxy-bin ./cmd/proxy

# Stage 2: Immagine di runtime leggera
FROM alpine:latest
WORKDIR /root/
COPY --from=builder /proxy-bin ./proxy
RUN chmod +x ./proxy

EXPOSE 8080
CMD ["./proxy"]