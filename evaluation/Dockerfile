FROM python:3.11-slim

WORKDIR /evaluation

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /evaluation

EXPOSE 9000

CMD ["python", "mock_gemini_server.py"]
