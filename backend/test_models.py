from app.config import GEMINI_API_KEY
from google import genai

client = genai.Client(api_key=GEMINI_API_KEY)
models_to_test = [
    'gemini-3.6-flash',
    'gemini-3.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
]

for m in models_to_test:
    try:
        resp = client.models.generate_content(model=m, contents='Say OK')
        print(f'{m}: SUCCESS -> {resp.text.strip()}')
    except Exception as e:
        print(f'{m}: FAILED -> {e}')
