# Partner Management staff-portal-api (staff/admin-facing). Build context = repo root.
FROM python:3.12-alpine

ARG FASTAPI_COMMON_REF=develop

RUN apk add --no-cache --virtual .build-deps gcc libc-dev linux-headers make \
 && apk add --no-cache bash git gettext libpq-dev libffi-dev openssl-dev

WORKDIR /app

RUN pip install --no-cache-dir \
    "git+https://github.com/openg2p/openg2p-fastapi-common.git@${FASTAPI_COMMON_REF}#subdirectory=openg2p-fastapi-common"

COPY core/api /src/api
RUN pip install --no-cache-dir /src/api

RUN apk del --no-network .build-deps

ENV PYTHONUNBUFFERED=1
ENV PARTNER_MANAGER_HOST=0.0.0.0
ENV PARTNER_MANAGER_PORT=8000
ENV PARTNER_MANAGER_NO_OF_WORKERS=2
ENV PARTNER_MANAGER_WORKER_TYPE=gunicorn

CMD python3 -m openg2p_partner_management_api.staff_portal_main migrate && \
    gunicorn "openg2p_partner_management_api.staff_portal_main:app" \
      --workers ${PARTNER_MANAGER_NO_OF_WORKERS} \
      --worker-class uvicorn.workers.UvicornWorker \
      --bind ${PARTNER_MANAGER_HOST}:${PARTNER_MANAGER_PORT} \
      --log-level info
