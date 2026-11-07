FROM python:3.12.8-slim
WORKDIR /app
RUN pip install --no-cache-dir boto3==1.35.81
COPY worker/worker.py worker/clean.py /app/
COPY prompts/teacher_prompt.txt /app/prompts/teacher_prompt.txt
USER 1000
ENTRYPOINT ["python", "-u", "/app/worker.py"]
