17 June 2025

📄 SEMentor Room Booking Application – Development Log (2025-06-17)

System Capabilities Implemented:

Feature	Status	Details
Natural language booking interface	✅	Single /assistant endpoint using LLM for parsing
Employee ID verification	✅	Validates format and existence from employees collection
Admin override	✅	Allows admins to bypass purpose conflict restrictions
Time overlap detection	✅	Detects partial and full overlaps
Purpose similarity check	✅	Uses embedding-based semantic similarity
Slot normalization	✅	Time ranges standardized to 12-hour format
Booking storage	✅	Bookings stored with metadata and embeddings
Cancellation support	✅	Deletes bookings based on ID, date, and time
View my bookings	✅	Filters bookings by employee_id
Available room query	✅	Returns list of free rooms for a given time slot
Unauthorized user handling	✅	Rejects bookings from unregistered employees


⸻

Database Collections:
	•	employees: 10 dummy employee profiles, with employee_id, name, department, and admin status.
	•	bookings: Stores room reservations with attendee count, time slot, purpose, and vector embeddings.

⸻

Testing Summary:
	•	✔ Booking works with valid EMP IDs and matching purpose
	•	✔ Admin override functions correctly
	•	✔ Cancellation deletes records from MongoDB
	•	✔ Partial time overlaps blocked
	•	✔ “Show my bookings” "Cancel my bookings" work as expected
	•	✔ No overlapping between bookings 
	•	Invalid EMP IDs (e.g., EMP9999)
	•	Unauthorized access
	•	Overlapping with unmatched purposes (non-admins)

⸻

Outstanding / Deferred:
	
	•	Rate limiting is not currently enforced
	•	Modifying bookings handled as cancel + book
	

⸻


