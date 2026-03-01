FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "agent_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
