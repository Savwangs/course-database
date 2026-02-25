<div align="center">

<h1>Skyrelis — DVC Course Assistant, CourseGenie</h1>

<p>
A cloud-based, PostgreSQL-backed course assistant that helps community college students search classes, filter sections, and get structured transfer-aware guidance.
</p>

<p>
<a href="#features">Features</a> •
<a href="#architecture">Architecture</a> •
<a href="#tech-stack">Tech Stack</a> •
<a href="#api-endpoints">API Endpoints</a> •
<a href="#database-schema-overview">Database Schema</a> •
<a href="#run-locally">Run Locally</a> •
<a href="#environment-variables">Environment Variables</a> •
<a href="#google-cloud-sql-notes">Google Cloud SQL Notes</a>
</p>

</div>

<hr/>

## Features

<ul>
  <li><b>Course search</b> with structured filters (keyword, modality, day, instructor)</li>
  <li><b>Section-first database design</b> backed by PostgreSQL</li>
  <li><b>AI assistant endpoint</b> for planning / transfer questions (OpenAI-backed)</li>
  <li><b>Interaction logging</b> stored in Postgres (prompt, summary, status, confidence, timestamp)</li>
  <li><b>Cloud-managed database</b> using <b>Google Cloud SQL</b> (managed PostgreSQL)</li>
</ul>

---

## Architecture

<ul>
  <li><b>Flask API</b> exposes endpoints for course search and AI assistance.</li>
  <li><b>SQLAlchemy models</b> define the live database schema.</li>
  <li><b>Service layer</b> (e.g., <code>CourseSearcher</code>) encapsulates filtering logic and response formatting.</li>
  <li><b>Logging layer</b> writes interaction records into <code>interaction_logs</code>.</li>
  <li><b>Database</b>:
    <ul>
      <li><b>Local development</b>: local PostgreSQL</li>
      <li><b>Production</b>: Google Cloud SQL (managed PostgreSQL)</li>
    </ul>
  </li>
</ul>

<blockquote>
<b>Note:</b> This repository is not currently Dockerized unless a <code>Dockerfile</code> exists in the root.  
Cloud Run deployments may still be used via source-based builds or an external build pipeline.
</blockquote>

---

## Tech Stack

<b>Backend</b>
<ul>
  <li>Python 3.11</li>
  <li>Flask</li>
  <li>SQLAlchemy</li>
  <li>psycopg2-binary</li>
  <li>python-dotenv</li>
  <li>OpenAI API</li>
</ul>

<b>Database</b>
<ul>
  <li>PostgreSQL</li>
  <li>Google Cloud SQL (PostgreSQL)</li>
</ul>

<b>Cloud / Infra</b>
<ul>
  <li>Google Cloud Run (deployment target)</li>
  <li>Cloud SQL Auth Proxy (recommended for secure local access to Cloud SQL)</li>
  <li>Cloud Build (optional CI/CD depending on workflow)</li>
</ul>

---

## API Endpoints

<details>
  <summary><b>GET /health</b> — Health check</summary>

  <br/>

  <b>Description</b>: Returns basic server status.  
  <b>Response</b> (example):
  <pre><code>{
  "status": "ok"
}</code></pre>
</details>

<details>
  <summary><b>GET /api/search</b> — Search course sections</summary>

  <br/>

  <b>Description</b>: Returns matching course sections based on filters.  
  <b>Query parameters</b> (all optional):
  <ul>
    <li><code>keyword</code> (string) — searches course title/subject/number/description (implementation-dependent)</li>
    <li><code>modality</code> (string) — online / hybrid / in-person</li>
    <li><code>day</code> (string)</li>
    <li><code>instructor</code> (string)</li>
  </ul>

  <b>Example</b>:
  <pre><code>GET /api/search?keyword=python&amp;modality=online</code></pre>

  <b>Response</b> (example):
  <pre><code>{
  "results": [
    {
      "subject": "COMSC",
      "course_number": "165",
      "title": "Python Programming",
      "section_number": "1234",
      "instructor": "Doe",
      "modality": "online",
      "days": "Asynchronous",
      "start_time": null,
      "end_time": null,
      "term": "Spring 2026"
    }
  ]
}</code></pre>
</details>

<details>
  <summary><b>POST /api/assistant</b> — AI assistant</summary>

  <br/>

  <b>Description</b>: Answers planning/transfer questions and logs the interaction.  
  <b>Request body</b>:
  <pre><code>{
  "prompt": "What classes should I take before transferring?"
}</code></pre>

  <b>Response</b> (example):
  <pre><code>{
  "response": "…",
  "confidence": "high"
}</code></pre>
</details>

---

## Database Schema Overview

Skyrelis currently uses a <b>section-first</b> schema (no separate course catalog table).  
The tables below reflect the models used in the codebase.

---

### course_sections

Stores section-level course offerings.

<table>
  <tr><th>Field</th><th>Type</th><th>Description</th></tr>
  <tr><td><code>id</code></td><td>Integer (PK)</td><td>Primary key</td></tr>
  <tr><td><code>subject</code></td><td>Text</td><td>Course subject (e.g., COMSC)</td></tr>
  <tr><td><code>course_number</code></td><td>Text</td><td>Course number (e.g., 165)</td></tr>
  <tr><td><code>title</code></td><td>Text</td><td>Course title</td></tr>
  <tr><td><code>section_number</code></td><td>Text</td><td>Section identifier</td></tr>
  <tr><td><code>instructor</code></td><td>Text</td><td>Instructor name</td></tr>
  <tr><td><code>modality</code></td><td>Text</td><td>Online / Hybrid / In-person</td></tr>
  <tr><td><code>days</code></td><td>Text</td><td>Meeting days</td></tr>
  <tr><td><code>start_time</code></td><td>Text</td><td>Start time</td></tr>
  <tr><td><code>end_time</code></td><td>Text</td><td>End time</td></tr>
  <tr><td><code>term</code></td><td>Text</td><td>Academic term</td></tr>
</table>

<blockquote>
If your <code>course_sections</code> model includes additional fields (CRN, location, capacity, etc.), add them here to keep the README accurate.
</blockquote>

---

### interaction_logs

Stores AI/system interaction logs.

<table>
  <tr><th>Field</th><th>Type</th><th>Description</th></tr>
  <tr><td><code>id</code></td><td>Integer (PK)</td><td>Primary key</td></tr>
  <tr><td><code>timestamp</code></td><td>DateTime (timezone-aware)</td><td>Defaults to UTC (server-side)</td></tr>
  <tr><td><code>project_name</code></td><td>Text</td><td>Module/feature tag</td></tr>
  <tr><td><code>user_prompt</code></td><td>Text</td><td>User input</td></tr>
  <tr><td><code>chatbot_response_summary</code></td><td>Text</td><td>Short response summary</td></tr>
  <tr><td><code>status</code></td><td>Text</td><td>success / error</td></tr>
  <tr><td><code>confidence_level</code></td><td>Text</td><td>high / medium / low</td></tr>
</table>

---

## Run Locally

### Prerequisites

<ul>
  <li>Python 3.11</li>
  <li>PostgreSQL (local) <i>or</i> Cloud SQL Auth Proxy</li>
  <li><code>pip</code> and a virtual environment tool (<code>venv</code> recommended)</li>
</ul>

---

### 1) Clone the repository
<pre><code>git clone https://github.com/&lt;your-username&gt;/skyrelis.git
cd skyrelis</code></pre>

---

### 2) Create and activate a virtual environment
<pre><code>python -m venv venv
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows</code></pre>

---

### 3) Install dependencies
<pre><code>pip install -r requirements.txt</code></pre>

---

### 4) Create a `.env` file
See <a href="#environment-variables">Environment Variables</a> below.

---

### 5) Database setup (choose one)

<details>
  <summary><b>Option A — Local PostgreSQL</b></summary>

  <br/>

  <b>Create the database</b>:
  <pre><code>createdb coursegenie_dev</code></pre>

  <b>Set DATABASE_URL</b>:
  <pre><code>DATABASE_URL=postgresql://&lt;user&gt;:&lt;password&gt;@localhost:5432/coursegenie_dev</code></pre>

</details>

<details>
  <summary><b>Option B — Google Cloud SQL (Recommended) via Cloud SQL Auth Proxy</b></summary>

  <br/>

  <b>1) Install Cloud SQL Auth Proxy</b>:
  <pre><code>brew install cloud-sql-proxy</code></pre>

  <b>2) Authenticate</b>:
  <pre><code>gcloud auth application-default login</code></pre>

  <b>3) Start the proxy</b>:
  <pre><code>cloud-sql-proxy &lt;INSTANCE_CONNECTION_NAME&gt; --port 5432</code></pre>

  <b>4) Set DATABASE_URL</b> (proxy exposes localhost):
  <pre><code>DATABASE_URL=postgresql://&lt;user&gt;:&lt;password&gt;@127.0.0.1:5432/&lt;db_name&gt;</code></pre>

</details>

---

### 6) Initialize tables

Use the approach that matches your repository:

<ul>
  <li>If you have a <code>migrations/</code> folder (Flask-Migrate/Alembic), run:</li>
</ul>

<pre><code>flask db upgrade</code></pre>

<ul>
  <li>If you create tables directly via SQLAlchemy (<code>db.create_all()</code>), run:</li>
</ul>

<pre><code>python -c "from app import app; from backend.models import db; app.app_context().push(); db.create_all(); print('tables created')"</code></pre>

---

### 7) Start the server
<pre><code>flask run</code></pre>

Server:
<pre><code>http://127.0.0.1:5000</code></pre>

---

## Environment Variables

Create a `.env` file in the project root.

<b>Required</b>
<pre><code>FLASK_ENV=development
PROJECT_NAME=skyrelis
DATABASE_URL=postgresql://&lt;user&gt;:&lt;password&gt;@localhost:5432/coursegenie_dev
OPENAI_API_KEY=&lt;your_key&gt;
</code></pre>

<b>Optional</b>
<pre><code>LOG_LEVEL=INFO</code></pre>

---

## Google Cloud SQL Notes

<ul>
  <li>Production uses <b>Google Cloud SQL</b> (managed PostgreSQL). The database server is managed by Google.</li>
  <li>Recommended access patterns:
    <ul>
      <li><b>Cloud Run</b> connects using the Cloud SQL connection integration (unix socket on the runtime)</li>
      <li><b>Local development</b> uses <b>Cloud SQL Auth Proxy</b> for secure tunneling</li>
    </ul>
  </li>
  <li>Do not commit secrets. Store them in:
    <ul>
      <li><b>Local</b>: <code>.env</code> (gitignored)</li>
      <li><b>Production</b>: Cloud Run environment variables and/or Secret Manager</li>
    </ul>
  </li>
</ul>

<b>Cloud Run DATABASE_URL pattern</b> (unix socket):
<pre><code>DATABASE_URL=postgresql://&lt;user&gt;:&lt;password&gt;@/&lt;db_name&gt;?host=/cloudsql/&lt;INSTANCE_CONNECTION_NAME&gt;</code></pre>

---

## Key Python Packages

<ul>
  <li><code>Flask</code></li>
  <li><code>SQLAlchemy</code></li>
  <li><code>psycopg2-binary</code></li>
  <li><code>python-dotenv</code></li>
  <li><code>openai</code></li>
</ul>

---
