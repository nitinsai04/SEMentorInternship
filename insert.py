import json
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["meeting_rooms"]
employees = db["employees"]

with open("employees_clean.json") as f:
    data = json.load(f)

employees.insert_many(data)