FROM python:3.14
WORKDIR /shiftrx_challenge

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
CMD ["python", "src/app/app.py"]
