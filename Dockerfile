FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
# NOTE: This file MUST exist in your project root
COPY requirements.txt .

# Install dependencies
# We use --no-cache-dir to minimize the size impact of doing the install in the final stage.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and data
COPY main.py .
COPY templates templates/
COPY static static/
COPY vocabulary vocabulary/

# Expose the port Uvicorn will run on
EXPOSE 8000

# Command to run the application using Uvicorn
# The executables (like 'uvicorn') are available in the path after a standard pip install
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]