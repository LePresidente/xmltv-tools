FROM python:3.7-alpine

RUN pip install redis tmdbv3api

WORKDIR '/XmltvEnhancer'
VOLUME ["/output"]

COPY ./XmltvEnhancer.py .

ENTRYPOINT ["python3", "./XmltvEnhancer.py"]
