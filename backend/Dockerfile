FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install project metadata/dependencies first for better Docker layer caching.
COPY pyproject.toml ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[test]"

# Copy the application source.
COPY app/ ./app/

# Copy the test source.
COPY tests/ ./tests/

# Copy Alembic configuration and migrations.
COPY alembic.ini ./
COPY alembic/ ./alembic/


# The backend listens on port 8000.
EXPOSE 8000

# Start the FastAPI application.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]