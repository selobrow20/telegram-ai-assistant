FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Environment setting
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

CMD ["python", "bot.py"]
