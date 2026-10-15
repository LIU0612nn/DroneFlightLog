FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    DEBUG=0

WORKDIR /app

# minimal system libs for matplotlib/reportlab rendering
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libfreetype6 libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py wsgi.py ./

RUN mkdir -p generated data/logs

EXPOSE 8080
CMD ["python", "wsgi.py"]
