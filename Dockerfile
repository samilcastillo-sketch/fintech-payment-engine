FROM python:3.13-slim

WORKDIR /app

# Ensure non-root user for security best practices
RUN useradd -m -u 1001 appuser

COPY src/ /app/src/

ENV PORT=8000 \
    HOST=0.0.0.0 \
    DATABASE_PATH=/app/data/payments.db \
    ENV=production

RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["python3", "-m", "src.server"]
