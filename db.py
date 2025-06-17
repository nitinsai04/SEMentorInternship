from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["meeting_rooms"]
bookings = db["bookings"]
employees = db["employees"]