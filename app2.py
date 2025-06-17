from flask import Flask, request, jsonify
from db import bookings
from db import employees
from utils import get_embedding, is_purpose_similar
from models import is_valid_room
from datetime import datetime, timedelta
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from typing import Optional

app = Flask(__name__)

class BookingDetails(BaseModel):
    room: Optional[str] = None
    attendees: Optional[int] = None
    date: Optional[str] = None
    time: Optional[str] = None
    purpose: Optional[str] = None
    employee_id: Optional[str] = None
    intent: str = "book"

prompt_template = """
You are a helpful office assistant. Extract the following from the user's input and respond with only a JSON object matching the specified format:
- Room name
- Number of people
- Date (convert any relative dates like 'tomorrow' or 'next Monday' to absolute YYYY-MM-DD format)
- Time slot
- Purpose
- Employee ID
- Intent: one of "book", "cancel", "view"

User: {user_input}
Respond only with a JSON object containing values for these fields, enclosed in triple backticks and formatted as valid JSON:
```json
{format_instructions}
```
"""

parser = PydanticOutputParser(pydantic_object=BookingDetails)
prompt = PromptTemplate(template=prompt_template, input_variables=["user_input"], partial_variables={"format_instructions": parser.get_format_instructions()}, output_parser=parser)

ollama = OllamaLLM(model="llama3.2")  # ensure model name matches your pulled model

import re

def times_overlap(start1, end1, start2, end2):
    return max(start1, start2) < min(end1, end2)

def parse_time_range(date_str, time_range):
    parts = time_range.split(" to ") if " to " in time_range else time_range.split(" - ")
    start = datetime.strptime(f"{date_str} {parts[0].strip()}", "%Y-%m-%d %I:%M %p")
    end = datetime.strptime(f"{date_str} {parts[1].strip()}", "%Y-%m-%d %I:%M %p")
    return start, end

@app.route("/book", methods=["POST"])
def book_room():
    data = request.json
    room = data["room"]
    date = data["date"]
    time = data["time"]
    attendees = data["attendees"]
    purpose = data["purpose"]
    booked_by = data["booked_by"]

    try:
        # Validate employee ID format
        if not re.match(r"^(EMP|ADMIN)\d{4}$", booked_by):
            return jsonify({
                "status": "fail",
                "reason": "Invalid Employee ID format. It must be in the form EMPxxxx or ADMINxxxx."
            }), 400

        # Check if employee exists in the employees collection
        emp_record = employees.find_one({"employee_id": booked_by})
        if not emp_record:
            return jsonify({
                "status": "fail",
                "reason": "Unauthorized: Employee ID not found in system."
            }), 403
        # 1. Validate room capacity
        if not is_valid_room(room, attendees):
            return jsonify({"status": "fail", "reason": "Room over capacity"}), 400

        # Parse the incoming time range
        try:
            start_time, end_time = parse_time_range(date, time)
        except Exception:
            return jsonify({"status": "fail", "reason": "Invalid time format. Use 'HH:MM AM/PM to HH:MM AM/PM' or 'HH:MM AM/PM - HH:MM AM/PM'."}), 400

        # 2. Check for existing bookings with time overlap by fetching all bookings for room and date
        existing_bookings = list(bookings.find({"room": room, "date": date}))
        for clash in existing_bookings:
            try:
                clash_start, clash_end = parse_time_range(clash["date"], clash["time"])
            except Exception:
                continue  # skip invalid time format in DB
            if times_overlap(start_time, end_time, clash_start, clash_end):
                similar, score = is_purpose_similar(purpose, clash["purpose"])
                if not similar and not booked_by.startswith("ADMIN"):
                    return jsonify({
                        "status": "fail",
                        "reason": "Purpose mismatch with existing booking",
                        "existing_booking": {
                            "room": clash["room"],
                            "date": clash["date"],
                            "time": clash["time"],
                            "purpose": clash["purpose"]
                        }
                    }), 409
                else:
                    return jsonify({
                        "status": "fail",
                        "reason": "Room is already booked at this time",
                        "existing_booking": {
                            "room": clash["room"],
                            "date": clash["date"],
                            "time": clash["time"],
                            "purpose": clash["purpose"]
                        }
                    }), 409

        # 3. All good – book it
        booking = {
            "room": room,
            "date": date,
            "time": time,
            "attendees": attendees,
            "purpose": purpose,
            "embedding": get_embedding(purpose).tolist(),
            "booked_by": booked_by
        }
        bookings.insert_one(booking)
        return jsonify({"status": "success", "booking": booking}), 200
    except Exception as e:
        return jsonify({"status": "error", "reason": "An unexpected error occurred", "error": str(e)}), 500

@app.route("/assistant", methods=["POST"])
def assistant():
    user_input = request.json["prompt"]
    formatted_prompt = prompt.format_prompt(user_input=user_input)
    llm_response = ollama.invoke(formatted_prompt.to_string())

# Log or print the raw response for debugging
    print("LLM Response:\n", llm_response)

    # Try parsing safely
    try:
        parsed_output = parser.parse(llm_response)
        # Enforce employee ID regex validation immediately after parsing for specific intents
        if parsed_output.intent in ["book", "cancel", "view"]:
            if not parsed_output.employee_id or not re.fullmatch(r"(EMP|ADMIN)\d{4}", parsed_output.employee_id):
                return jsonify({
                    "status": "error",
                    "message": "Invalid Employee ID format. It must be in the form EMPxxxx or ADMINxxxx.",
                    "parsed": parsed_output.dict()
                }), 400
            emp_record = employees.find_one({"employee_id": parsed_output.employee_id})
            if not emp_record:
                return jsonify({
                    "status": "error",
                    "message": "Unauthorized: Employee ID not found in system.",
                    "parsed": parsed_output.dict()
                }), 403

        # Check for view intent
        if hasattr(parsed_output, "intent") and parsed_output.intent == "view":
            emp_id = parsed_output.employee_id
            if not emp_id or not re.fullmatch(r"(EMP|ADMIN)\d{4}", emp_id):
                return jsonify({
                    "status": "error",
                    "message": "Invalid Employee ID format. It must be in the form EMPxxxx or ADMINxxxx.",
                    "parsed": parsed_output.dict()
                }), 400

            user_bookings = list(bookings.find({"booked_by": emp_id}, {"_id": 0, "embedding": 0}))
            return jsonify({
                "status": "success",
                "employee_id": emp_id,
                "bookings": user_bookings
            })

        if parsed_output.intent == "cancel":
            result = bookings.delete_one({
                "booked_by": parsed_output.employee_id,
                "date": parsed_output.date,
                "time": parsed_output.time
            })
            if result.deleted_count == 0:
                return jsonify({
                    "status": "fail",
                    "message": "No matching booking found to cancel"
                }), 404
            return jsonify({
                "status": "success",
                "message": f"Booking on {parsed_output.date} at {parsed_output.time} for {parsed_output.employee_id} has been cancelled."
            })

        if parsed_output.intent == "availability":
            if not parsed_output.date or not parsed_output.time:
                return jsonify({
                    "status": "error",
                    "message": "Please provide both date and time to check availability.",
                    "parsed": parsed_output.dict()
                }), 400

            try:
                desired_start, desired_end = parse_time_range(parsed_output.date, parsed_output.time)
            except Exception:
                return jsonify({
                    "status": "error",
                    "message": "Invalid time format. Use 'HH:MM AM/PM to HH:MM AM/PM' or 'HH:MM AM/PM - HH:MM AM/PM'.",
                    "parsed": parsed_output.dict()
                }), 400

            all_rooms = ["Brainstorm Hub", "Data Dome", "Conference Room"]
            booked_rooms = set()
            for b in bookings.find({"date": parsed_output.date}):
                try:
                    start, end = parse_time_range(b["date"], b["time"])
                    if times_overlap(desired_start, desired_end, start, end):
                        booked_rooms.add(b["room"])
                except Exception:
                    continue

            available = [r for r in all_rooms if r not in booked_rooms]
            return jsonify({
                "status": "success",
                "available_rooms": available,
                "date": parsed_output.date,
                "time": parsed_output.time
            })

        # Check room capacity
        if not is_valid_room(parsed_output.room, parsed_output.attendees):
            return jsonify({
                "status": "error",
                "message": f"{parsed_output.room} cannot accommodate {parsed_output.attendees} people. Please reduce the number of attendees or choose another room.",
                "parsed": parsed_output.dict()
            }), 400

        try:
            dt = datetime.fromisoformat(parsed_output.time)
            start = dt.strftime("%I:%M %p").lstrip("0")
            end_dt = dt + timedelta(hours=1)
            end = end_dt.strftime("%I:%M %p").lstrip("0")
            parsed_output.time = f"{start} to {end}"
        except Exception:
            pass
        
        # Parse the time range for overlap checking
        try:
            start_time, end_time = parse_time_range(parsed_output.date, parsed_output.time)
        except Exception:
            return jsonify({
                "status": "error",
                "message": "Invalid time format. Use 'HH:MM AM/PM to HH:MM AM/PM' or 'HH:MM AM/PM - HH:MM AM/PM'.",
                "parsed": parsed_output.dict()
            }), 400

        # Check for existing bookings with time overlap by fetching all bookings for room and date
        existing_bookings = list(bookings.find({"room": parsed_output.room, "date": parsed_output.date}))
        for clash in existing_bookings:
            try:
                clash_start, clash_end = parse_time_range(clash["date"], clash["time"])
            except Exception:
                continue  # skip invalid time format in DB
            if times_overlap(start_time, end_time, clash_start, clash_end):
                similar, score = is_purpose_similar(parsed_output.purpose, clash["purpose"])
                if not similar and not parsed_output.employee_id.startswith("ADMIN"):
                    return jsonify({
                        "status": "fail",
                        "reason": "Purpose mismatch with existing booking",
                        "existing_booking": {
                            "room": clash["room"],
                            "date": clash["date"],
                            "time": clash["time"],
                            "purpose": clash["purpose"]
                        }
                    }), 409
                else:
                    return jsonify({
                        "status": "fail",
                        "reason": "Room is already booked at this time",
                        "existing_booking": {
                            "room": clash["room"],
                            "date": clash["date"],
                            "time": clash["time"],
                            "purpose": clash["purpose"]
                        }
                    }), 409
        
        booking = {
            "room": parsed_output.room,
            "date": parsed_output.date,
            "time": parsed_output.time,
            "attendees": parsed_output.attendees,
            "purpose": parsed_output.purpose,
            "embedding": get_embedding(parsed_output.purpose).tolist(),
            "booked_by": parsed_output.employee_id
        }
        bookings.insert_one(booking)
        
        message = f"{parsed_output.attendees} people can use {parsed_output.room} on {parsed_output.date} from {parsed_output.time} to {parsed_output.purpose.lower()}."
        return jsonify({
            "status": "success",
            "parsed": parsed_output.dict(),
            "raw_response": llm_response,
            "message": message,
            "mongo_inserted": True
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Failed to parse LLM response",
            "llm_output": llm_response,
            "error": str(e)
        }), 500

if __name__ == "__main__":
    app.run(debug=True)