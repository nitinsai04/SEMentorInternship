from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import requests

model = SentenceTransformer('all-MiniLM-L6-v2')

def get_embedding(text):
    return model.encode([text])[0]

def is_purpose_similar(p1, p2, threshold=0.75):
    emb1 = get_embedding(p1)
    emb2 = get_embedding(p2)
    sim = cosine_similarity([emb1], [emb2])[0][0]
    return sim > threshold, sim

def query_ollama(prompt):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3", "prompt": prompt, "stream": False}
    )
    return response.json()["response"].strip()