import httpx
from groq import Groq
from dotenv import load_dotenv
import os

http_client = httpx.Client(verify=False)
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
print(api_key)
client = Groq(
    api_key="YOUR_API_KEY",
    http_client=http_client
)