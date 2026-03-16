FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY schedule_analyst/ ./schedule_analyst/
COPY server.py .
COPY brain/ ./brain/
COPY static/ ./static/

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

# Port for Cloud Run (Cloud Run sets PORT env var)
ENV PORT=8080
EXPOSE 8080

# Run unified ADK + static server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "120"]
