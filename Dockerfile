FROM python:3-buster
ENV PYTHONUNBUFFERED=1

RUN apt update && apt install -y vim
COPY requirements.txt *py /opt/app/
RUN pip3 install -r /opt/app/requirements.txt
CMD /opt/app/miner_exporter.py
