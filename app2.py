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
from flask_cors import CORS
from bson import ObjectId


app = Flask(__name__)
CORS(app)
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
- Time slot (strictly use 12-hour format like 'HH:MM AM/PM to HH:MM AM/PM' or 'HH:MM AM/PM - HH:MM AM/PM'; do not use 24-hour format)
- Purpose
- Employee ID
- Intent: one of "book", "cancel", "view"
Respond ONLY with a **valid JSON object**, enclosed in triple backticks. DO NOT add extra explanation, markdown, or bullet points.
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
        # Attempt to clean malformed JSON if parsing fails
        llm_cleaned = re.sub(r"```json|```", "", llm_response).strip()
        try:
            parsed_output = parser.parse(llm_cleaned)
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": "Failed to parse cleaned LLM response",
                "llm_output": llm_response,
                "error": str(e)
            }), 500
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

            user_bookings = list(bookings.find({"booked_by": emp_id}, {"embedding": 0}))
            for b in user_bookings:
                b["_id"] = str(b["_id"])
            return jsonify({
                "status": "success",
                "employee_id": emp_id,
                "bookings": user_bookings
            })

        if parsed_output.intent == "cancel":
            try:
                start_time, end_time = parse_time_range(parsed_output.date, parsed_output.time)
                start_str = f"{start_time.hour % 12 or 12}:{start_time.strftime('%M %p')}"
                end_str = f"{end_time.hour % 12 or 12}:{end_time.strftime('%M %p')}"
                normalized_time = f"{start_str} to {end_str}"
            except Exception:
                normalized_time = parsed_output.time.strip()

            print(f"Attempting to cancel with: emp={parsed_output.employee_id}, room={parsed_output.room}, date={parsed_output.date}, time={normalized_time}")

            result = bookings.delete_one({
                "booked_by": parsed_output.employee_id,
                "room": parsed_output.room,
                "date": parsed_output.date,
                "time": normalized_time
            })

            if result.deleted_count == 0:
                return jsonify({
                    "status": "fail",
                    "message": "No matching booking found to cancel"
                }), 404

            return jsonify({
                "status": "success",
                "message": f"Booking on {parsed_output.date} at {normalized_time} for {parsed_output.employee_id} has been cancelled."
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

# --- Login route for verification ---
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    emp_id = data.get("employee_id")
    password = data.get("password")

    if not emp_id or not password:
        return jsonify({"status": "fail", "reason": "Missing employee ID or password"}), 400

    emp_record = employees.find_one({"employee_id": emp_id})
    if not emp_record:
        return jsonify({"status": "fail", "reason": "Employee ID not found"}), 404

    if emp_record["password"] != password:
        return jsonify({"status": "fail", "reason": "Incorrect password"}), 401

    return jsonify({
        "status": "success",
        "employee_id": emp_record["employee_id"],
        "name": emp_record["name"],
        "is_admin": emp_record.get("is_admin", False)
    }), 200


@app.route("/invite", methods=["POST"])
def invite_employees():
    data = request.get_json()
    print("Invite payload received:", data)

    booking_id = data.get("booking_id")
    invitees = data.get("invitees")  # List of employee_ids

    if not booking_id or not invitees:
        return jsonify({
            "status": "fail",
            "reason": f"Missing booking_id or invitees. Received: {data}"
        }), 400

    # Add each invitee with status "sent" into the invites array
    result = bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$addToSet": {"invites": {"$each": [{"employee_id": emp_id, "status": "sent"} for emp_id in invitees]}}}
    )

    if result.matched_count == 0:
        return jsonify({"status": "fail", "reason": "Booking not found"}), 404

    return jsonify({
        "status": "success",
        "message": f"Invited {invitees} to booking {booking_id}"
    }), 200

# --- Route for employees to view all their received invites ---
@app.route("/my_invites", methods=["POST"])
def get_invites():
    emp_id = request.json.get("employee_id")
    invites = []
    # Find all bookings that have the specified employee ID in the 'invites' array
    matching_bookings = bookings.find({
        "invites": {
            "$elemMatch": {"employee_id": emp_id}
        }
    }, {"embedding": 0})

    for booking in matching_bookings:
        for invite in booking.get("invites", []):
            if invite.get("employee_id") == emp_id:
                inviter_record = employees.find_one({"employee_id": booking["booked_by"]})
                inviter_name = inviter_record["name"] if inviter_record else booking["booked_by"]
                invite_copy = {
                    "booking_id": str(booking["_id"]),
                    "room": booking["room"],
                    "date": booking["date"],
                    "time": booking["time"],
                    "purpose": booking["purpose"],
                    "status": invite.get("status", "sent"),
                    "invited_by": inviter_name
                }
                invites.append(invite_copy)

    print(f"Invites fetched for {emp_id}: {invites}")
    return jsonify({"status": "success", "invites": invites}), 200

# --- Route to update invite status for a booking ---
@app.route("/respond_invite", methods=["POST"])
def respond_invite():
    data = request.get_json()
    booking_id = data.get("booking_id")
    emp_id = data.get("employee_id")
    new_status = data.get("status")

    if not booking_id or not emp_id or not new_status:
        return jsonify({"status": "fail", "reason": "Missing fields"}), 400

    result = bookings.update_one(
        {"_id": ObjectId(booking_id), "invites.employee_id": emp_id},
        {"$set": {"invites.$.status": new_status}}
    )

    if result.matched_count == 0:
        return jsonify({"status": "fail", "reason": "Invite not found"}), 404

    return jsonify({"status": "success", "message": f"Invite for {emp_id} updated to {new_status}"}), 200

# --- Route to get all employees for dropdown population ---
@app.route("/employees", methods=["GET"])
def get_employees():
    employee_list = list(employees.find({}, {"_id": 0, "employee_id": 1, "name": 1}))
    return jsonify({"employees": employee_list}), 200

if __name__ == "__main__":
    app.run(debug=True)