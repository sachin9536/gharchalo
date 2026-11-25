FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 app
USER 10001

EXPOSE 8000
# Seeding is a separate step (compose "seed" service / Helm seed Job): python seed.py --if-empty --wait 60
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
