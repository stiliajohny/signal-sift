FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home appuser
COPY config ./config
USER 10001
EXPOSE 8000
CMD ["uvicorn", "alert_insight.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
