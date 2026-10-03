# Sandbox image for the Cosmic Python "allocation" app.
#
# It holds only Python and the packages the tests need, never the app's code:
# the code is mounted read-only at /work for every single check. So the image
# is built once and stays valid no matter what the agent changes.
#
# Python 3.9 + SQLAlchemy 1.4 because that is what the target repository was
# written for (see its own Dockerfile and requirements.txt).
FROM python:3.9-slim

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
 && useradd --uid 1000 --create-home runner

# Checks run as this normal user (the harness also passes --user 1000:1000).
USER runner
