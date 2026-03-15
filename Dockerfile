FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY schedule_analyst/ ./schedule_analyst/
COPY main.py .
COPY brain/ ./brain/

# Port for Cloud Run
ENV PORT=8080
EXPOSE 8080

# Run the HTTP server via gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "main:app"]
