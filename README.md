# SEMentor Room Booking Assistant

A smart, LLM-powered meeting room reservation assistant for internal teams at **SE Mentor**, supporting natural language booking, admin overrides, availability queries, and semantic conflict resolution.

---

## ✅ Features Implemented

| Feature                           | Status | Description |
|----------------------------------|--------|-------------|
| Natural language booking         | ✅     | Handles free-text queries via `/assistant` endpoint using LLM (LLaMA 3.2) |
| Employee ID verification         | ✅     | Matches `EMPxxxx` / `ADMINxxxx` formats and cross-checks MongoDB |
| Admin override                   | ✅     | Admins can bypass semantic purpose restrictions |
| Time overlap detection           | ✅     | Detects full and **partial** slot conflicts |
| Purpose similarity check         | ✅     | Embedding-based check to detect duplicate or related meetings |
| Slot normalization               | ✅     | Ensures consistent formatting to `HH:MM AM/PM - HH:MM AM/PM` |
| Booking storage                  | ✅     | Embedding + metadata stored in `bookings` collection |
| Cancellation support             | ✅     | Cancels bookings via natural language |
| View my bookings                 | ✅     | Filters bookings by employee ID |
| Room availability check          | ✅     | Returns list of unbooked rooms at a specified time |
| Unauthorized access rejection    | ✅     | Ensures only registered employees can make requests |

---

## 🗃️ Database Schema

### `employees` collection
Stores employee metadata and access level.

```json
{
  "employee_id": "EMP1001",
  "name": "Nitin Sai",
  "email": "nitin.sai@sementor.com",
  "department": "Engineering",
  "designation": "Software Engineer",
  "password": "pass1234",
  "is_admin": false
}
