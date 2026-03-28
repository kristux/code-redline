FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY review_server.py .
COPY review_home.html .
COPY review_ui.html .
COPY static/ static/

RUN mkdir -p reviews

EXPOSE 7890

CMD ["python", "-m", "uvicorn", "review_server:app", "--host", "0.0.0.0", "--port", "7890"]
