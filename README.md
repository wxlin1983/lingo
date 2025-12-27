# wlingo - A Simple Quiz App

Wlingo is a simple and intuitive web application designed to help you learn new vocabulary or practice arithmetic through interactive quizzes. It's built with FastAPI and provides a clean, user-friendly interface.

## Features

- **Multiple Quiz Modes:** Choose between vocabulary quizzes from various topics or test your skills with arithmetic problems.
- **Customizable Vocabulary:** Easily add your own vocabulary sets by creating simple CSV files.
- **Interactive Quizzes:** Engage with a clean and simple quiz interface.
- **REST API:** Access quiz data and topics through a RESTful API.
- **API Documentation:** Explore and test the API with the automatically generated Swagger UI documentation.
- **Containerized Deployment:** Run the application in a Docker container for easy deployment.

## Getting Started

You can run this application either directly on your machine using Python or with Docker.

### Prerequisites

- Python 3.11+
- `uv` (or `pip`) for package installation
- Docker (optional, for containerized deployment)

### 1. Installation & Setup

First, clone the repository to your local machine:

```bash
git clone https://github.com/your-username/wlingo.git
cd wlingo
```

Next, install the required Python packages. It is recommended to use a virtual environment.

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies using uv (faster)
uv pip install -r requirements.txt

# Or using pip
pip install -r requirements.txt
```

### 2. Running the Application

#### With Docker Compose (Recommended)

The easiest way to get the application and its Redis dependency running is with Docker Compose.

1.  **Build and Run the Services:**

    Make sure you have Docker and Docker Compose installed, then run the following command from the project root:

    ```bash
    docker-compose up --build
    ```

    This will build the Docker image for the web app, pull the Redis image, and start both services. The `-d` flag can be added to run in detached mode.

2.  **Stopping the Services:**

    To stop the services, press `Ctrl+C` in the terminal where `docker-compose` is running, or run `docker-compose down` if you are in detached mode.

#### Without Docker

To run the app directly, you'll need to set the `PYTHONPATH` to include the `src` directory.

```bash
PYTHONPATH=src uvicorn wlingo.main:app --host 0.0.0.0 --port 8000 --reload
```

The `--reload` flag automatically restarts the server when you make code changes.

#### With Docker

If you prefer using Docker, you can build and run a container.

1.  **Build the Docker Image:**

    ```bash
    docker build -t wlingo .
    ```

2.  **Run the Container:**

    ```bash
    docker run -d -p 8000:8000 --name wlingo-instance wlingo
    ```

### 3. Accessing the Application

Once the server is running, you can access the application in your web browser:

-   **Start Quiz:** [http://localhost:8000](http://localhost:8000)
-   **API Docs (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)

## Customization

### Adding Vocabulary Topics

You can add your own vocabulary topics by creating `.csv` files in the `src/vocabulary/` directory. Each file represents a new topic, and the filename (without the extension) will be used as the topic name.

The CSV file must contain `word` and `translation` columns.

**Example: `src/vocabulary/Spanish.csv`**

```csv
word,translation
hola,hello
adiós,goodbye
gracias,thank you
```

The application will automatically load the new topics when it starts.

### Configuration

You can customize the application's behavior by modifying the settings in `src/wlingo/config.py`. This file contains settings for the session timeout, test size, logging, and more.
