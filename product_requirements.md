# Email Agentic AI — Product Specification & Roadmap

**Author:** Omer (project owner)
**Created:** 2025-08-12
**Purpose:** Full product specification, architecture, privacy/security notes, MVP scope, tech stack, and an executable 6–8 week roadmap to build a LinkedIn-worthy AI-powered email assistant (classification, auto-reply, summarisation, prioritisation).

---

## 1. Elevator pitch

A privacy-conscious, agentic AI web application that connects to Gmail, **classifies** incoming emails (Job Alerts, Opportunities, Marketing, Personal, Spam, Important), **summarises** long threads, **ranks priority**, and optionally drafts/sends **auto-replies** in your tone. Built as a modular agent architecture so components (Classifier, Summariser, Auto-Reply) can be extended and re-used.

Goal: a clean, demo-ready product that showcases modern AI skills (LLM orchestration, embeddings & vector search, LangChain-like agents, secure OAuth, FastAPI backend, Next.js frontend) without costing much — prefer free/open-source alternatives where practical.

---

## 2. Core features (MVP)

- Gmail integration (OAuth): read, label, send.
- Automated classification into categories and custom labels.
- Thread summarisation (short bullets + 1-line TL;DR).
- Priority/urgency scoring (low/medium/high) and filtering.
- UI dashboard to view categories, thread summaries, and quick actions.
- Manual reply composer and one-click AI draft reply.
- Basic auto-reply rules (e.g., when "In Meeting" or away).
- Local dev mode and clear instructions to run without sharing personal data with external vendors (option to use local LLMs).

---

## 3. Extended features (v1+)

- Fine-tuning/personalisation of replies using your own sent emails (privacy-first).
- Vector database for semantic search across emails (Weaviate / Milvus / SQLite+FAISS local options).
- Bulk unsubscribe / archive suggestions (marketing cleanup agent).
- Job-alert extractor that stores job posts in a separate feed.
- Analytics: processed emails, accuracy estimate, reply acceptance rate.
- Role-based access if you want multiple users later.

---

## 4. Agent design (high-level)

Agents are modular processes that receive email content + metadata and return actions or structured outputs.

### Agents

- **Ingest Agent**: fetches emails, canonicalises text, strips signatures (optional), stores raw + metadata.
- **Classifier Agent**: assigns category labels using an LLM or a smaller classifier model.
- **Priority Agent**: scores urgency using rules + LLM heuristics (sender importance, keywords, deadlines, thread depth).
- **Summariser Agent**: generates short summary and TL;DR per thread.
- **Auto-Reply Agent**: crafts reply drafts using templates + prompt-engineered LLM or local model; supports send-on-approval or auto-send rules.
- **Policy Agent**: enforces privacy, checks for PII, compliance with do-not-reply lists.

Agents communicate through an internal message bus (simple: DB rows + background workers; advanced: message queue like Redis/RQ or RabbitMQ).

---

## 5. Data model (simplified)

- `User` (id, email, oauth_tokens_encrypted, settings)
- `Email` (id, thread_id, from, to, subject, body_plain, body_html, received_at, raw_json)
- `Label` (email_id, name, confidence)
- `Summary` (email_id, summary_text, generated_at)
- `Action` (email_id, agent, action_type, status)

Encryption: OAuth tokens and any sensitive fields stored encrypted at rest (AES-256) with keys from environment or secret manager.

---

## 6. Recommended tech stack (cost-sensitive & CV-friendly)

**Backend**

- Language: **Python** (strong in AI ecosystem)
- Framework: **FastAPI** (async, fast, modern)
- Worker: **RQ** with Redis (or simple threaded background tasks for MVP)
- Gmail client: `google-api-python-client` + OAuth2
- Agent orchestration: **LangChain** / **LlamaIndex** for quick integration; however, design your code so the orchestration logic is modular. That way, if you later want to replace LangChain with a custom orchestrator (Option B), you can do so without rewriting everything.
- Hosted LLMs (if using cloud): **OpenAI** (paid) with redaction/pseudonymisation steps

**Vector DB / Embeddings**

- Free/local: **FAISS (on-disk)**, **SQLite+FAISS**

**Frontend**

- **Next.js** (React); styling with **Tailwind CSS** (shadcn) (clean and modern) or Material UI
- Component: dashboard, email view, summary panel, quick-actions, settings

**DB / Storage**

- **PostgreSQL** (Heroku free tier / Supabase for hobby)

**Dev / Deployment (low cost)**

- Frontend: **Vercel** (free tier)
- Backend: **Render** / **Railway** free tier or small EC2/Heroku dyno
- Secrets: environment variables

**CI/CD** (In future not now)

- GitHub Actions for automated tests and deploys

---

## 7. Privacy & security (very important)

You said you don't want to freely share data with OpenAI — here are approaches:

### Option A — Minimal exposure (hybrid)

- **Redact** or pseudonymise emails before sending to OpenAI (strip names, emails, phone numbers, attachments). Use regex + heuristic PII detection.
- Send only the minimal text needed for classification/summarisation. For example, use subject + first 200–400 chars + selected sentences.
- Keep a local cache of redaction rules and allow user to opt-out per label.

### Option C — Encryption & data governance

- Encrypt tokens & sensitive DB fields at rest.
- Use end-to-end encryption for stored email bodies if desired (adds complexity).
- Add a privacy toggle in the UI: `Use cloud LLMs (faster)` vs `Use local/private LLMs (more private)`.

### Audit & logging

- Log actions but never log full email body in plaintext logs.
- Maintain an audit trail of automated sends and a manual verification flow for auto-sends.

---

## 8. MVP scope & acceptance criteria

**MVP Scope**

- Gmail OAuth connection and read-only ingest of the last 500 emails.
- Classifier Agent that labels at least 5 categories with a simple LLM prompt or small model.
- UI to show categories, an email thread viewer with generated summary, and one-click AI draft reply.
- Auto-reply rules limited to an "Away / In meeting" template that can be toggled on/off.

**Acceptance criteria**

- Successful OAuth connect + ingest (Test: connect to a test Gmail account)
- 80%+ perceived usefulness of summaries in user testing (subjective; test with 10 threads)
- Dashboard loads under 2s for small dataset
- Auto-reply never sends without explicit approval in MVP (safe default)

---

## 9. 6–8 Week Roadmap (week-by-week)

**Week 0 (Prep)**

- Repo init, license, README skeleton.
- Create Google Cloud project, enable Gmail API, register OAuth consent for test account.

**Week 1 (Ingest & Storage)**

- Backend skeleton (FastAPI). Implement OAuth flow and ingest endpoint.
- Store emails in DB. Simple UI page showing raw emails.

**Week 2 (Classifier MVP)**

- Implement Classifier Agent using prompt to OpenAI or local model.
- Add labels in DB and UI filtering.

**Week 3 (Summariser + Priority)**

- Add summariser agent for threads.
- Implement simple priority score (rules + model)
- UI: thread view with summary + priority indicator.

**Week 4 (Auto-Reply Drafts)**

- Add Auto-Reply Agent producing drafts (UI shows draft, user can edit & send).
- Add templates & tone-preserving prompt methodology.

**Week 5 (Polish & Privacy Options)**

- Implement redaction/pseudonymisation pipeline.
- Add settings UI: choose cloud vs local LLM, toggles for auto-send.
- Add basic tests and CI with GitHub Actions.

**Week 6 (Demo & Deployment)**

- Deploy frontend (Vercel) + backend (Render/Railway).
- Create demo video GIFs, screenshots, and a LinkedIn post draft with metrics.
- Prepare README and project repo for sharing.

**Optional Week 7–8 (Advanced)**

- Add vector search for semantic queries.
- Implement fine-tune / personalization using user's sent folder (carefully).
- Add analytics dashboard and email summarisation improvements.

---

## 10. Developer workflow & repo structure (current)

```
  /backend          - FastAPI backend application
    app/
      main.py
      api/
      agents/
      workers/
      models/
      db/
  /src              - Next.js frontend application
  /public           - Static frontend assets
  /node_modules     - Frontend dependencies
  package.json      - Frontend package configuration
  next.config.ts    - Next.js configuration
  tsconfig.json     - TypeScript configuration
  tailwind.config.* - Tailwind CSS configuration
  .gitignore        - Git ignore rules (frontend + backend)
  README.md         - Project documentation
  product_requirements.md - This specification document
```

Use Docker for local reproducibility. Provide a `dev` script to start backend, frontend, and a Redis worker.

---

## 11. Testing & evaluation

- Unit tests for data parsing, redaction, and agent interfaces.
- Integration tests for OAuth flow (mock tokens) and send flow (send to test mailbox).
- Manual user evaluation for summaries & classification on a small dataset.
- Track metrics: emails processed / minute, average latency per agent, user acceptance of draft replies.

---

## 12. Demo & LinkedIn guidance

- Record short demo: 60–90s GIF showing 1) connecting Gmail 2) categories 3) one long thread summarised 4) draft reply generated and sent.
- Share architecture diagram, key tech stack points, and a short write-up: problems solved, technical choices, and privacy options.
- Suggest highlighting: agent orchestration, local LLM privacy option, OAuth security, and CI/CD deployment.

---

## 13. Cost considerations (how to keep it cheap)

- Use free tiers: Vercel (frontend), Render/Railway hobby plans, Supabase (free DB), GitHub Actions free minutes.
- Use OpenAI sparingly for initial classification/summarisation; prefer local models or distilled smaller models for continuous background tasks.
- Use local vector DB (FAISS/Chroma) instead of paid Pinecone for demo-scale data.

---

## 14. Repo README (short template)

- Project purpose & problem statement
- Quick start (local dev with Docker)
- OAuth setup instructions (how to create Google project & get client_id/secret)
- How to switch between cloud LLM and local LLM
- Privacy notes and recommended safe defaults

---

## 15. Next steps (what I can help you with)

- I can generate the project skeleton code (FastAPI backend + simple Next.js frontend) with OAuth mock and local dev instructions.
- I can write prompt templates for classification, summarisation, and reply drafting.
- I can prepare a LinkedIn demo post text + GIF storyboard.

---

## 16. Appendix — Prompt ideas (short)

**Classifier prompt (example)**

- "You are an email classifier. The email subject and body are: <SUBJECT> <BODY>. Output one of: JOB, OPPORTUNITY, MARKETING, PERSONAL, SPAM, IMPORTANT. Also output a short one-line reason."

**Summariser prompt (example)**

- "Summarise this email thread in 3 bullet points and a 1-line TL;DR. Keep it neutral tone. THREAD: <THREAD_TEXT>"

**Auto-reply prompt (example)**

- "Write a concise reply in Omer's tone (short, polite, professional). Context: <SUMMARY>. Sender asked: <QUESTION>. Reply should: acknowledge, state unavailability if away, offer follow-up time or ask for more info."

---

_End of document._
