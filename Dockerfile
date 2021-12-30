FROM python:3.10.1-slim-buster

WORKDIR /app
COPY . .

RUN apt-get update -y && apt-get upgrade -y 
RUN apt-get install -y libgmp3-dev gcc

RUN pip install -r requirements.txt

CMD uvicorn denaro.node.main:app --port 3006 --workers 2