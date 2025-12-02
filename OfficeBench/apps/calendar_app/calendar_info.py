# information on calendar functionalities
from apps.calendar_app.calendar_create_event import DEMO as create_event_demo
from apps.calendar_app.calendar_delete_event import DEMO as delete_event_demo
from apps.calendar_app.calendar_list_events import DEMO as list_event_demo

class CalendarInfo:
    def __init__(self):
        self.name = "calendar"
        self.info = {
            "create_event": create_event_demo,
            "delete_event": delete_event_demo,
            "list_events": list_event_demo,
        }
        
    def get_instruction(self) -> str:
        instructions = [f"Command to perform function: {key}:\n{demo}" for key, demo in self.info.items()]
        return f"## How to use the {self.name} app:\n\n" + "\n\n".join(instructions)