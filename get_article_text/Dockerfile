FROM continuumio/anaconda3

RUN apt-get update -y
RUN apt-get install -y python-dev libxml2-dev libxslt-dev libpq-dev gcc

# attach current dir
ADD . .

# install requirements
RUN pip install -r ./requirements.txt

RUN curl https://raw.githubusercontent.com/codelucas/newspaper/master/download_corpora.py | python
EXPOSE 8000

ENTRYPOINT ["gunicorn", "app:app", "--workers", "8", "--bind", "0.0.0.0:8000", "--limit-request-line", "0", "--worker-class", "gevent", "--timeout", "300"]

