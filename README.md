# Reddit Insight Miner ⛏️

Extract pain points, buying intent, and product ideas from any Reddit thread using AI.

## How It Works

1. Paste any Reddit thread URL
2. The tool fetches all comments via Reddit's `.json` endpoint
3. GPT-4 analyzes the thread to extract:
   - **Pain Points** - Problems people are complaining about (with severity ratings)
   - **Buying Intent** - Signals that people want to pay for solutions
   - **Unmet Needs** - Gaps in existing solutions
   - **Objections & Concerns** - What makes people hesitant
   - **Patterns** - Recurring themes and sentiments
   - **Product Ideas** - Actionable opportunities with MVP suggestions
   - **Golden Quotes** - The most insightful quotes (testimonial gold)
   - **Next Steps** - Specific actions to take

## Local Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key (optional - works without it too)
export OPENAI_API_KEY="sk-your-key-here"

# Run the app
python app.py
```

Then open http://localhost:5050

## Deploy to Production

### Railway (Recommended)
1. Push code to GitHub
2. Connect repo to [Railway](https://railway.app)
3. Add environment variable: `OPENAI_API_KEY`
4. Deploy!

### Render
1. Push code to GitHub
2. Create new Web Service on [Render](https://render.com)
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `gunicorn app:app`
5. Add environment variable: `OPENAI_API_KEY`

### Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | No | Enables automatic AI analysis |
| `PORT` | No | Server port (default: 5050) |
| `FLASK_DEBUG` | No | Set to `false` in production |

## Features

- ✅ **Rate limiting** - 10 requests/minute per IP
- ✅ **Caching** - Results cached for 1 hour
- ✅ **No API key mode** - Copy prompt to use with any LLM
- ✅ **Production ready** - Gunicorn + proper error handling

## Tips

- Niche subreddits are gold: try r/SaaS, r/Entrepreneur, r/smallbusiness
- Threads with 50+ comments give better insights
- Look for "what tool do you use for X" or "I wish there was a..." posts

## No OpenAI Key?

No problem! The tool will:
1. Fetch and format the thread data
2. Generate a ready-to-use analysis prompt
3. Give you one-click copy to paste into ChatGPT, Claude, or any LLM

