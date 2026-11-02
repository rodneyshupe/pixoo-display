FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir paho-mqtt tzdata
WORKDIR /app
COPY app/pixoo_display /app/pixoo_display
COPY seed_gifs /app/seed_gifs
CMD ["python", "-m", "pixoo_display"]
