# The pipeline and the agent as one small image. Airflow runs the same code from dags/.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bookings bookings
COPY sql sql
COPY agent agent
ENV BOOKINGS_ROOT=/data
VOLUME /data
ENTRYPOINT ["python", "-m", "bookings", "--root", "/data"]
