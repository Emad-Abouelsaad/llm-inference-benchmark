FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY llmbench ./llmbench
COPY sql ./sql
COPY prompts ./prompts

ENTRYPOINT ["python", "-m", "llmbench"]
CMD ["--help"]
