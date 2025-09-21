import os, json
import requests
# Handle both relative and absolute imports
try:
    from .config import OPENAI_API_KEY
except ImportError:
    from config import OPENAI_API_KEY
try:
    from .prompt_templates import SUMMARY_PROMPT
except ImportError:
    from prompt_templates import SUMMARY_PROMPT

# Lazy initialization of OpenAI client
_client = None

def get_openai_client():
    global _client
    if _client is None:
        print("🤖 Initializing OpenAI client...")
        try:
            # Create a custom OpenAI client for compatibility
            class SimpleOpenAIClient:
                def __init__(self, api_key):
                    self.api_key = api_key
                    
                def chat_completions_create(self, **kwargs):
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                    
                    data = {
                        "model": kwargs.get("model", "gpt-4o-mini"),
                        "messages": kwargs.get("messages", []),
                        "temperature": kwargs.get("temperature", 0.0),
                        "max_tokens": kwargs.get("max_tokens", 400)
                    }
                    
                    response = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=data,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        return response.json()
                    else:
                        raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
            
            _client = SimpleOpenAIClient(OPENAI_API_KEY)
            print("✅ OpenAI client initialized (custom client)")
            
        except Exception as e:
            print(f"❌ OpenAI client initialization failed: {e}")
            raise e
    return _client

def ask_llm(incident: dict, related_items: list):
    try:
        related_text = ""
        if related_items and isinstance(related_items, list):
            for it in related_items:
                if isinstance(it, dict):
                    similarity = it.get('similarity', 0)
                    summary = (it.get('summary') or '')[:200]
                    service = it.get('service', 'unknown')
                    labels = it.get('labels', [])
                    
                    # Include solutions from similar incidents
                    solution = it.get('solution', '')
                    
                    related_text += f"• Similar incident (similarity: {similarity})\n"
                    related_text += f"  Service: {service} | Summary: {summary}\n"
                    related_text += f"  Labels: {labels}\n"
                    
                    if solution:
                        related_text += f"  Solution: {solution}\n"
                    else:
                        related_text += f"  Solution: Not provided yet\n"
                    related_text += "\n"
        
        prompt = SUMMARY_PROMPT.format(
            service = incident.get("evidence", {}).get("service") if isinstance(incident.get("evidence"), dict) else "unknown",
            timestamp = incident.get("created_at") or "",
            labels = incident.get("labels") or [],
            summary = incident.get("summary_text") or "",
            evidence = str(incident.get("evidence", "")) if incident.get("evidence") else "",
            related_list = related_text or "None"
        )
        
        client = get_openai_client()
        
        # Make API call with proper error handling
        try:
            # Use custom client
            response = client.chat_completions_create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":prompt}],
                temperature=0.0,
                max_tokens=400
            )
            text = response['choices'][0]['message']['content'].strip()
            
        except Exception as api_error:
            print(f"❌ OpenAI API call failed: {api_error}")
            # Return a meaningful fallback response
            return {
                "summary": f"Analysis failed for incident: {incident.get('summary_text', 'Unknown')[:100]}. Manual review required.",
                "root_causes": [
                    {
                        "cause": "Automated analysis unavailable",
                        "fixes": ["Manual incident review required", "Check system logs", "Contact on-call engineer"],
                        "rollback": "No automatic fixes available"
                    }
                ],
                "confidence": "low"
            }
        
        try:
            start = text.find("{")
            end = text.rfind("}")+1
            json_text = text[start:end]
            return json.loads(json_text)
        except Exception:
            return {"summary": text[:400], "root_causes": [], "confidence": "low"}
    
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return {
            "summary": f"Error analyzing incident: {incident.get('summary_text', 'Unknown incident')}", 
            "root_causes": [], 
            "confidence": "low"
        }