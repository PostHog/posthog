FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY relay.py .
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["python", "relay.py"]
CMD ["serve"]
