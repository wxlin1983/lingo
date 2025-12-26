FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and data
COPY src/static static/
COPY src/wlingo wlingo/
COPY src/templates templates/
COPY src/vocabulary vocabulary/

# Expose the port Uvicorn will run on
EXPOSE 8000

ENV PYTHONPATH=src
# Command to run the application using Uvicorn
CMD ["uvicorn", "wlingo.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]