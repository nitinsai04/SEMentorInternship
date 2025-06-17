from flask import Flask, request, jsonify
from db import bookings
from utils import get_embedding, is_purpose_similar
from models import is_valid_room
from datetime import datetime, timedelta
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel

app = Flask(__name__)

class BookingDetails(BaseModel):
    room: str
    attendees: int
    date: str
    time: str
    purpose: str
    employee_id: str

prompt_template = """
You are a helpful office assistant. Extract the following from the user's input and respond with only a JSON object matching the specified format:
- Room name
- Number of people
- Date (convert any relative dates like 'tomorrow' or 'next Monday' to absolute YYYY-MM-DD format)
- Time slot
- Purpose
- Employee ID

User: {user_input}
Respond only with a JSON object containing values for these fields, enclosed in triple backticks and formatted as valid JSON:
```json
{format_instructions}
```
"""

parser = PydanticOutputParser(pydantic_object=BookingDetails)
prompt = PromptTemplate(template=prompt_template, input_variables=["user_input"], partial_variables={"format_instructions": parser.get_format_instructions()}, output_parser=parser)

ollama = OllamaLLM(model="llama3.2")  # ensure model name matches your pulled model

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
        # 1. Validate room capacity
        if not is_valid_room(room, attendees):
            return jsonify({"status": "fail", "reason": "Room over capacity"}), 400

        # 2. Check for existing bookings
        clash = bookings.find_one({"room": room, "date": date, "time": time})
        if clash:
            similar, score = is_purpose_similar(purpose, clash["purpose"])
            if not similar:
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
        if (
            not parsed_output.employee_id or
            parsed_output.employee_id.lower() in [
                "none", "null", "xxx", "not provided", "missing"
            ]
        ):
            return jsonify({
                "status": "error",
                "message": "Employee ID is missing or invalid. Please provide a valid Employee ID to proceed with the booking.",
                "parsed": parsed_output.dict()
            }), 400

        # Check room capacity
        if not is_valid_room(parsed_output.room, parsed_output.attendees):
            return jsonify({
                "status": "error",
                "message": f"{parsed_output.room} cannot accommodate {parsed_output.attendees} people. Please reduce the number of attendees or choose another room.",
                "parsed": parsed_output.dict()
            }), 400

        try:
            dt = datetime.fromisoformat(parsed_output.time)
            start = dt.strftime("%H:%M")
            end = (dt + timedelta(hours=1)).strftime("%H:%M")
            parsed_output.time = f"{start}-{end}"
        except Exception:
            pass
        
        # Check for existing bookings
        clash = bookings.find_one({
            "room": parsed_output.room,
            "date": parsed_output.date,
            "time": parsed_output.time
        })
        if clash:
            similar, score = is_purpose_similar(parsed_output.purpose, clash["purpose"])
            if not similar:
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