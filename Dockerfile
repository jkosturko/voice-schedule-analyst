FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY schedule_analyst/ ./schedule_analyst/
COPY main.py .
COPY brain/ ./brain/

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

# Port for Cloud Run (Cloud Run sets PORT env var)
ENV PORT=8080
EXPOSE 8080

# Run the HTTP server via gunicorn
# --workers 2: enough for Cloud Run's single vCPU
# --timeout 120: allow time for Calendar API + Gemini calls
# --access-logfile -: log requests to stdout for Cloud Logging
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "main:app"]
