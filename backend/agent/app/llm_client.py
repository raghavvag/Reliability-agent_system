import os, json
from openai import OpenAI
from .config import OPENAI_API_KEY
from .prompt_templates import SUMMARY_PROMPT

client = OpenAI(api_key=OPENAI_API_KEY)

def ask_llm(incident: dict, related_items: list):
    try:
        related_text = ""
        for it in related_items:
            related_text += f"- id:{it.get('memory_id')} | service:{it.get('service')} | summary:{(it.get('summary') or '')[:200]} | labels:{it.get('labels')}\n"
        
        prompt = SUMMARY_PROMPT.format(
            service = incident.get("evidence", {}).get("service") or incident.get("summary_text",""),
            timestamp = incident.get("created_at") or "",
            labels = incident.get("labels") or [],
            summary = incident.get("summary_text") or "",
            evidence = (incident.get("evidence") or {}) if isinstance(incident.get("evidence"), dict) else incident.get("evidence",""),
            related_list = related_text or "None"
        )
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",   # change model if needed
            messages=[{"role":"user","content":prompt}],
            temperature=0.0,
            max_tokens=400
        )
        
        text = response.choices[0].message.content.strip()
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
