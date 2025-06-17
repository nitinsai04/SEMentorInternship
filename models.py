ROOM_CAPACITY = {
    "Brainstorm Hub": 6,
    "Data Dome": 4,
    "Pinnacle":2
}
def is_valid_room(room, attendees):
    return ROOM_CAPACITY.get(room, 0) >= attendees