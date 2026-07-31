FROM alpine:latest
WORKDIR /root/
# Copia il binario già compilato dalla tua macchina
COPY proxy-bin ./proxy
RUN chmod +x ./proxy

EXPOSE 8080
CMD ["./proxy"]