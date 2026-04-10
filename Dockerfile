FROM python:3.11-slim

WORKDIR /app

# Install dependencies before copying source for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Run as non-root user
RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "agent_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
