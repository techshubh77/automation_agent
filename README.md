# Automation Agent API 🚀

Hey there! Welcome to the **Automation Agent** backend repository. 

If you're reading this, you probably need to get this project up and running on your local machine. Don't worry, we've set this up to be as painless and developer-friendly as possible. This project is built on a highly structured, enterprise-grade MVC foundation using Python's modern ecosystem.

---

## 🛠 What's under the hood?

Before we start, here's a quick look at the tech stack you'll be working with:
- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Blazing fast, async-first Python framework)
- **Database:** PostgreSQL (using `asyncpg` for non-blocking database calls)
- **ORM:** SQLAlchemy 2.0 (The modern, strongly-typed way)
- **Migrations:** Alembic
- **Package Manager:** `uv` (The extremely fast Python package manager)
- **Task Runner:** `just` (A cross-platform alternative to `make`)

---

## 💻 Prerequisites

To run this project, you'll need a few things installed on your machine first:
1. **Python 3.13+**
2. **PostgreSQL** (running locally or via Docker on port 5432)
3. **Qdrant** (Vector Database, run via Docker: `docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant`)
4. **[uv](https://docs.astral.sh/uv/)** (Python's new blazing-fast package manager)
5. **[just](https://just.systems/)** (Our task runner. You can install it on Mac via `brew install just`, or on Linux via `curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/.local/bin`)

---

## 🚀 Getting Started

Follow these steps to get the server running locally.

### 1. Clone & Install Dependencies
First, pull down the code and let `uv` handle installing all the packages.
```bash
# Clone the repository and jump in
git clone <repo-url>
cd automation-agent

# Sync all dependencies (this takes less than a second with uv!)
uv sync
```

### 2. Set up your Environment
We need to tell the app how to connect to your local database and set up some security keys.
```bash
# Copy the example environment file
cp .env.example .env
```
Open up the new `.env` file in your editor. You'll need to update the `DATABASE_URL` to point to your local Postgres database. It should look something like this:
`DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/automation_db"`

You also need an OpenAI API key for the AI features:
```env
OPENAI_API_KEY="sk-proj-..."
```

### 3. Run Database Migrations
Let's generate the tables in your database. Our `just` runner makes this incredibly simple.
```bash
# Run all pending migrations
just migrate
```

### 4. Boot it up!
You're ready to go. Start the development server:
```bash
just dev
```
The server is now running! 
- You can access the API at `http://localhost:3000`
- You can view the automatic interactive API Documentation (Swagger) at **`http://localhost:3000/docs`**

---

## 🧑‍💻 Daily Cheat Sheet

We use `just` to handle all our common terminal commands so you don't have to memorize long scripts. Here are the commands you'll use day-to-day:

| Command | What it does |
|---|---|
| `just dev` | Starts the local dev server with auto-reload enabled. |
| `just migration "message"` | Generates a new database migration file after you modify a table. |
| `just migrate` | Pushes pending migrations to your database. |
| `just format` | Auto-formats your code to keep the repo clean (using `ruff`). |
| `just test` | Runs the test suite. |

---

## 🔒 Security Notes
- **Never commit the `.env` file.** It is ignored by Git on purpose.
- **Rate Limiting** is applied globally. If you spam the API locally, you might get temporarily blocked. 

## 🧪 How to Test the AI Features

We built a **RAG (Retrieval-Augmented Generation)** pipeline. Here is how you can test it from end-to-end using the built-in Swagger UI:

1. **Start the server:** `just dev`
2. **Open Swagger:** Go to [http://localhost:3000/docs](http://localhost:3000/docs)
3. **Ingest Data (Step 1):** 
   - Open `POST /api/v1/ingestion/json`
   - Upload any JSON file containing data (e.g., policy documents, rules).
   - This will parse the JSON, chunk it, embed it using OpenAI, and save the vectors to Qdrant.
4. **Chat with Data (Step 2):**
   - Open `POST /api/v1/chat/`
   - Send a JSON payload like:
     ```json
     {
       "message": "What does the document say about X?"
     }
     ```
   - The API will perform a similarity search in Qdrant (threshold `0.5`, top 3 chunks) and stream the context to OpenAI to answer your question!

---

If you run into any weird errors during setup, just ask one of the core maintainers. Happy coding! ☕️
