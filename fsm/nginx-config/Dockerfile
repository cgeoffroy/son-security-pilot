FROM python:3.5-slim
MAINTAINER support@sonata-nfv.eu

# configurations
ENV mongo_host mongo
ENV mongo_port 27017
ENV broker_host amqp://guest:guest@broker:5672/%2F
ENV broker_exchange son-kernel

#// TO RUN IN THE LOCAL FILE (ex, for unitary tests)
RUN apt-get clean \
    && apt-get update \
    && apt-get install -y wget \
    && apt-get install -y git build-essential libffi-dev libssl-dev apt-utils \
    && wget https://download.docker.com/linux/static/stable/x86_64/docker-17.12.0-ce.tgz \
    && tar -xzf docker-*-ce.tgz \
    && cp docker/docker /usr/bin/ \
    && rm -rf docker-*-ce.tgz docker \
    && apt-get clean

RUN apt-get update && apt-get install nginx -y

RUN git clone --recursive https://github.com/sonata-nfv/son-sm.git
RUN git clone --recursive https://github.com/miguelmesquita/son-security-pilot.git

WORKDIR /son-sm/son-mano-framework/son-mano-base
RUN python setup.py install

WORKDIR /son-sm/son-sm-template
RUN python setup.py install

WORKDIR /son-security-pilot
ADD fsm/nginx-config /nginx-config

WORKDIR /nginx-config
RUN python setup.py develop

#WORKDIR /son-security-pilot/fsm/nginx-config/
COPY ansible/roles/nginx/files /etc/nginx

COPY ansible/roles/nginx/files/entrypoint.sh /sbin
RUN chmod 755 /sbin/entrypoint.sh

CMD ["fsm-nginx"]
#ENTRYPOINT ["tail", "-f", "/dev/null"]
