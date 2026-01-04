from flask import Flask, render_template, request, jsonify
import requests
import os
from openai import OpenAI
import json
import re
import hashlib
import uuid
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from cachetools import TTLCache

app = Flask(__name__)

# Rate limiting: 10 requests per minute per IP
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["100 per hour"],
    storage_uri="memory://"
)

# Cache results for 1 hour (max 100 entries)
analysis_cache = TTLCache(maxsize=100, ttl=3600)

# Shared results cache (24 hour TTL, max 500 entries)
share_cache = TTLCache(maxsize=500, ttl=86400)

def get_cache_key(url):
    """Generate cache key from URL"""
    return hashlib.md5(url.encode()).hexdigest()

def get_openai_client(api_key=None):
    """Get OpenAI client with optional user-provided key"""
    # Prefer user-provided key, fall back to environment variable
    key = api_key or os.environ.get('OPENAI_API_KEY')
    if key:
        return OpenAI(api_key=key)
    return None

def normalize_reddit_url(url):
    """Convert various Reddit URL formats to the JSON endpoint"""
    # Remove query params
    url = url.split('?')[0]
    # Remove trailing slash
    url = url.rstrip('/')
    # Handle old.reddit.com, www.reddit.com, reddit.com
    url = re.sub(r'https?://(old\.|www\.)?reddit\.com', 'https://www.reddit.com', url)
    # Add .json if not present
    if not url.endswith('.json'):
        url += '.json'
    return url

def is_thread_url(url):
    """Check if URL is a specific thread vs just a subreddit"""
    # Thread URLs contain /comments/
    return '/comments/' in url

def fetch_reddit_thread(url):
    """Fetch Reddit thread as JSON"""
    json_url = normalize_reddit_url(url)
    headers = {
        'User-Agent': 'RedditInsightsTool/1.0 (Educational Purpose)'
    }
    response = requests.get(json_url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()

def extract_comments(data, max_depth=10):
    """Recursively extract all comments from Reddit JSON"""
    comments = []
    
    def process_thing(thing, depth=0):
        if depth > max_depth:
            return
        if not isinstance(thing, dict):
            return
            
        kind = thing.get('kind')
        data = thing.get('data', {})
        
        if kind == 'Listing':
            children = data.get('children', [])
            for child in children:
                process_thing(child, depth)
        elif kind == 't3':  # Post
            comments.append({
                'type': 'post',
                'title': data.get('title', ''),
                'body': data.get('selftext', ''),
                'author': data.get('author', '[deleted]'),
                'score': data.get('score', 0),
                'url': data.get('url', ''),
                'num_comments': data.get('num_comments', 0),
                'created_utc': data.get('created_utc', 0),
                'subreddit': data.get('subreddit', '')
            })
        elif kind == 't1':  # Comment
            body = data.get('body', '')
            if body and body != '[deleted]' and body != '[removed]':
                comments.append({
                    'type': 'comment',
                    'body': body,
                    'author': data.get('author', '[deleted]'),
                    'score': data.get('score', 0),
                    'depth': depth
                })
            # Process replies
            replies = data.get('replies')
            if replies and isinstance(replies, dict):
                process_thing(replies, depth + 1)
    
    # Reddit returns a list with [post, comments]
    if isinstance(data, list):
        for item in data:
            process_thing(item)
    else:
        process_thing(data)
    
    return comments

def format_for_llm(comments):
    """Format extracted comments for LLM analysis"""
    parts = []
    
    for c in comments:
        if c['type'] == 'post':
            parts.append(f"=== POST (r/{c['subreddit']}) ===")
            parts.append(f"Title: {c['title']}")
            if c['body']:
                parts.append(f"Body: {c['body']}")
            parts.append(f"Score: {c['score']} | Comments: {c['num_comments']}")
            parts.append("")
        else:
            indent = "  " * c['depth']
            parts.append(f"{indent}[Score: {c['score']}] {c['body'][:500]}")
    
    return "\n".join(parts)

def analyze_with_llm(formatted_text, subreddit="", user_api_key=None):
    """Use OpenAI to extract insights"""
    openai_client = get_openai_client(user_api_key)
    if not openai_client:
        return {
            'no_api_key': True,
            'raw_data': formatted_text,
            'prompt': f"""You are an expert product researcher. Analyze this Reddit thread from r/{subreddit} to extract precise, actionable insights.

THREAD DATA:
{formatted_text[:12000]}

ANALYSIS RULES:
- Only include insights DIRECTLY supported by quotes from the thread
- Prioritize high-upvote comments — these are validated opinions  
- Look for emotional language (frustration, desperation, excitement) — signals real pain
- Distinguish "nice to have" vs "hair on fire" problems
- Be SPECIFIC: "People want better tools" = useless. "3 people said they'd pay $50/mo for X" = gold

EXTRACT THE FOLLOWING:

1. PAIN POINTS (for each one include):
   - The specific problem (be concrete, not vague)
   - Severity: critical / high / medium / low
   - How many people mentioned it
   - Who has this problem (customer profile)
   - How they currently solve it & why that fails
   - Exact quotes as evidence

2. BUYING INTENT:
   - What they explicitly want to pay for
   - Any budget/price hints
   - Urgency level
   - Exact quotes showing willingness to pay

3. UNMET NEEDS:
   - Things people want but say don't exist
   - Why it's unmet
   - Product opportunity to fill the gap
   - Exact quotes

4. OBJECTIONS & CONCERNS:
   - What makes people hesitant
   - How a product could overcome this

5. PATTERNS:
   - Recurring themes or behaviors
   - What this means for product builders

6. PRODUCT IDEAS (for each):
   - Specific idea (not vague)
   - Target customer
   - Which pain point it solves
   - MVP suggestion (simplest version to test)
   - Risks / why it might fail

7. GOLDEN QUOTES:
   - The most insightful, emotional, or actionable quotes (testimonial gold)

8. RECOMMENDED NEXT STEPS:
   - 2-3 specific actions based on this research

If the thread lacks good insights, say so honestly. Quality > quantity."""
        }
    
    prompt = f"""You are an expert product researcher. Analyze this Reddit thread from r/{subreddit} to extract precise, actionable insights for someone looking to build products or services.

THREAD DATA:
{formatted_text[:12000]}

ANALYSIS RULES:
- Only include insights that are DIRECTLY supported by quotes from the thread
- Prioritize comments with high upvotes (score) — these represent validated opinions
- Look for emotional language (frustration, excitement, desperation) — these signal real pain
- Distinguish between "nice to have" and "hair on fire" problems
- Ignore generic/joke comments

Provide your analysis in this exact JSON format:

{{
    "summary": "2-3 sentences: What is this thread about? What's the overall sentiment?",
    
    "pain_points": [
        {{
            "pain": "Specific, concrete problem (not vague)",
            "severity": "critical | high | medium | low",
            "frequency": "Number of people who mentioned this or similar",
            "who_has_it": "What type of person experiences this problem?",
            "current_solutions": "How are they solving it now (if mentioned)?",
            "why_current_solutions_fail": "Why existing solutions don't work",
            "quotes": ["Exact quote 1", "Exact quote 2"],
            "validation": "Why this is a real problem worth solving"
        }}
    ],
    
    "buying_intent": [
        {{
            "signal": "What they explicitly want to pay for",
            "budget_hints": "Any mentions of price, willingness to pay, or budget?",
            "urgency": "high | medium | low — how urgently do they need this?",
            "quotes": ["Exact quote showing intent to pay or buy"]
        }}
    ],
    
    "unmet_needs": [
        {{
            "need": "Something people want but explicitly say doesn't exist or is hard to find",
            "who_needs_it": "Target customer profile",
            "why_unmet": "Why hasn't this been solved yet?",
            "opportunity": "Specific product/service idea to fill this gap",
            "quotes": ["Exact quote"]
        }}
    ],
    
    "objections_and_concerns": [
        {{
            "objection": "What makes people hesitant or skeptical?",
            "how_to_overcome": "How could a product address this concern?",
            "quotes": ["Exact quote"]
        }}
    ],
    
    "patterns": [
        {{
            "pattern": "Recurring theme, behavior, or sentiment",
            "frequency": "How often this appeared",
            "implication": "What this means for product builders"
        }}
    ],
    
    "product_ideas": [
        {{
            "idea": "Specific, concrete product or feature idea",
            "target_customer": "Who exactly would buy this?",
            "problem_solved": "Which pain point(s) does this address?",
            "evidence": "Why this would work based on the thread",
            "mvp_suggestion": "Simplest version you could build to test this",
            "risk": "What could go wrong or why this might not work"
        }}
    ],
    
    "golden_quotes": [
        "The most insightful, emotional, or actionable quotes from the thread — these are testimonial gold"
    ],
    
    "recommended_next_steps": [
        "Specific action item 1 based on this research",
        "Specific action item 2"
    ]
}}

IMPORTANT:
- Be SPECIFIC, not generic. "People want better tools" is useless. "3 people said they'd pay $50/month for automated invoice reconciliation" is gold.
- Every insight must have supporting quotes
- Prioritize quality over quantity — only include high-signal insights
- If the thread doesn't have good insights, say so honestly"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert at extracting business insights from online discussions. You identify pain points, buying intent, and product opportunities. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        result['raw_data'] = formatted_text
        return result
        
    except Exception as e:
        return {
            'error': f'LLM analysis failed: {str(e)}',
            'raw_data': formatted_text
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
@limiter.limit("10 per minute")
def analyze():
    try:
        data = request.get_json()
        url = (data.get('url') or '').strip()
        user_api_key = (data.get('api_key') or '').strip() or None
        
        if not url:
            return jsonify({'error': 'Please provide a Reddit URL'}), 400
        
        if 'reddit.com' not in url:
            return jsonify({'error': 'Please provide a valid Reddit URL'}), 400
        
        if not is_thread_url(url):
            return jsonify({
                'error': 'Please paste a specific thread URL, not a subreddit. Example: reddit.com/r/SaaS/comments/abc123/thread_title'
            }), 400
        
        # Check cache first (only for server-analyzed results, not user-key results)
        cache_key = get_cache_key(url)
        if not user_api_key and cache_key in analysis_cache:
            return jsonify(analysis_cache[cache_key])
        
        # Fetch the thread
        reddit_data = fetch_reddit_thread(url)
        
        # Extract comments
        comments = extract_comments(reddit_data)
        
        if not comments:
            return jsonify({'error': 'No content found in this thread'}), 400
        
        # Get subreddit name
        subreddit = ""
        for c in comments:
            if c['type'] == 'post':
                subreddit = c.get('subreddit', '')
                break
        
        # Format for LLM
        formatted = format_for_llm(comments)
        
        # Analyze with user's API key or server key
        insights = analyze_with_llm(formatted, subreddit, user_api_key)
        insights['comment_count'] = len([c for c in comments if c['type'] == 'comment'])
        insights['subreddit'] = subreddit
        
        # Cache the result (only for server-analyzed results)
        if not insights.get('no_api_key') and not user_api_key:
            analysis_cache[cache_key] = insights
        
        return jsonify(insights)
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Failed to fetch Reddit thread: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

@app.route('/scan-subreddit', methods=['POST'])
@limiter.limit("5 per minute")
def scan_subreddit():
    """Scan a subreddit for top threads to analyze"""
    try:
        data = request.get_json()
        subreddit = data.get('subreddit', '').strip()
        
        # Clean subreddit name
        subreddit = subreddit.replace('r/', '').replace('/', '')
        
        if not subreddit:
            return jsonify({'error': 'Please provide a subreddit name'}), 400
        
        # Fetch top threads from subreddit
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=15"
        headers = {
            'User-Agent': 'RedditInsightsTool/1.0 (Educational Purpose)'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        reddit_data = response.json()
        
        threads = []
        children = reddit_data.get('data', {}).get('children', [])
        
        for child in children:
            post = child.get('data', {})
            # Skip pinned/stickied posts and posts with few comments
            if post.get('stickied') or post.get('num_comments', 0) < 5:
                continue
                
            threads.append({
                'title': post.get('title', '')[:100],
                'url': f"https://reddit.com{post.get('permalink', '')}",
                'score': post.get('score', 0),
                'num_comments': post.get('num_comments', 0),
                'created_utc': post.get('created_utc', 0)
            })
        
        # Sort by engagement (comments * score)
        threads.sort(key=lambda x: x['num_comments'] * (1 + x['score'] / 100), reverse=True)
        
        return jsonify({
            'subreddit': subreddit,
            'threads': threads[:10]
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Failed to fetch subreddit: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Scan failed: {str(e)}'}), 500


@app.route('/share', methods=['POST'])
@limiter.limit("10 per minute")
def share_results():
    """Create a shareable link for analysis results"""
    try:
        data = request.get_json()
        
        # Generate unique share ID
        share_id = str(uuid.uuid4())[:8]
        
        # Store in cache
        share_cache[share_id] = data
        
        return jsonify({'share_id': share_id})
        
    except Exception as e:
        return jsonify({'error': f'Failed to create share link: {str(e)}'}), 500


@app.route('/s/<share_id>')
def view_shared(share_id):
    """View shared analysis results"""
    if share_id in share_cache:
        # Render the index page with pre-loaded data
        return render_template('shared.html', data=share_cache[share_id])
    else:
        return render_template('index.html')  # Fallback to main page


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'error': 'Too many requests. Please wait a minute before trying again.'
    }), 429

if __name__ == '__main__':
    # Use debug mode only in development
    debug_mode = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=debug_mode, host='0.0.0.0', port=port)

