FROM python:3.14

## Install Ollama (Ubuntu/Debian)
#RUN apt-get update && apt-get install -y curl \
#    && curl -fsSL https://ollama.com/install.sh | sh \
#    && rm -rf /var/lib/apt/lists/*
#
## Pull the model at build time (the model is baked into Docker container \
## for POC simplicity, it's not an ideal production configuration)
#RUN ollama serve & \
#    for i in $(seq 1 30); do \
#      curl -sSf http://127.0.0.1:11434/api/tags && break || sleep 1; \
#    done && \
#    ollama pull llama3.2:3b-instruct-q4_K_S && \
#    pkill ollama || true

WORKDIR /shiftrx_challenge
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy in source files
COPY . .

EXPOSE 5000
ENV PYTHONPATH=/shiftrx_challenge/src

# Run
#CMD ["sh", "-c", "ollama serve & python src/app/app.py"]
CMD ["sh", "-c", "python src/app/app.py"]