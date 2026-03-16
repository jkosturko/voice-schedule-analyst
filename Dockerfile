FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN useradd --create-home appuser

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent package (includes server.py, static/, calendar_tools, agent, etc.)
COPY schedule_analyst/ ./schedule_analyst/
COPY brain/ ./brain/

# Non-root user
USER appuser

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080
EXPOSE 8080

# Run our custom server that merges ADK agent API + custom UI + Flask-like endpoints
# Shell form so $PORT is expanded at runtime (Cloud Run may override PORT)
CMD python -m uvicorn schedule_analyst.server:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 120
