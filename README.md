# Mail Mind AI

A privacy-conscious, agentic AI web application that connects to Gmail, classifies incoming emails, summarizes long threads, ranks priority, and optionally drafts/sends auto-replies in your tone.

## Project Structure

```
/backend          - FastAPI backend with AI agents
/src              - Next.js frontend application
/public           - Static assets
product_requirements.md - Full project specification
```

## Features

- Gmail integration (OAuth): read, label, send
- Automated email classification into categories
- Thread summarization (bullets + TL;DR)
- Priority/urgency scoring and filtering
- AI-powered auto-reply drafts
- Privacy-first design with local LLM options

## Getting Started

### Frontend Development

First, install dependencies and run the development server:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### Backend Development

Navigate to the backend directory and follow the setup instructions:

```bash
cd backend
# Setup instructions will be added as backend development progresses
```

## Tech Stack

- **Frontend**: Next.js, React, Tailwind CSS
- **Backend**: FastAPI, Python
- **Database**: PostgreSQL
- **AI/ML**: LangChain, OpenAI/Local LLMs
- **Authentication**: Gmail OAuth2

## Documentation

See `product_requirements.md` for the complete project specification, architecture, and development roadmap.

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
